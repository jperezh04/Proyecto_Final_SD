import grpc
from concurrent import futures
import bank_pb2
import bank_pb2_grpc
import json
import os
import uuid
from datetime import datetime, timezone
import threading
import time

# ---------- CONFIGURACIÓN ----------
NODE_ID = "chile"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")
PENDING_DIR = os.path.join(DATA_DIR, "pending")  # Para transacciones 2PC en curso

# ---------- PERSISTENCIA ----------
def load_account(account_id):
    path = os.path.join(ACCOUNTS_DIR, f"{account_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)

def save_account(account_id, data):
    path = os.path.join(ACCOUNTS_DIR, f"{account_id}.json")
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)

def save_pending(tx_id, data):
    """Guarda una transacción pendiente en disco (para recuperación)."""
    path = os.path.join(PENDING_DIR, f"{tx_id}.json")
    with open(path, "w") as f:
        json.dump(data, f)

def remove_pending(tx_id):
    path = os.path.join(PENDING_DIR, f"{tx_id}.json")
    if os.path.exists(path):
        os.remove(path)

# ---------- SERVICIO gRPC ----------
class BankService(bank_pb2_grpc.BankServiceServicer):
    def __init__(self):
        self.node_state = {
            "node_id": NODE_ID,
            "leader_id": None,
            "state": "FOLLOWER",
            "last_heartbeat": time.time()
        }
        self.pending_2pc = {}          # transacciones en memoria
        self.account_locks = {}        # bloqueos por cuenta
        self.global_lock = threading.Lock()  # para crear locks nuevos

    def _get_lock(self, account_id):
        """Devuelve (o crea) el lock para una cuenta."""
        with self.global_lock:
            if account_id not in self.account_locks:
                self.account_locks[account_id] = threading.Lock()
            return self.account_locks[account_id]

    # ---------- OPERACIONES BÁSICAS (sin cambios) ----------
    def GetBalance(self, request, context):
        account = load_account(request.account_id)
        if not account:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return bank_pb2.BalanceResponse()
        return bank_pb2.BalanceResponse(
            account_id=request.account_id,
            balance=account["balance"],
            currency=account["currency"]
        )

    def Deposit(self, request, context):
        lock = self._get_lock(request.account_id)
        with lock:
            account = load_account(request.account_id)
            if not account:
                return bank_pb2.TransactionResponse(success=False, message="Account not found")
            account["balance"] += request.amount
            account["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_account(request.account_id, account)
            return bank_pb2.TransactionResponse(
                success=True,
                message="Deposit successful",
                new_balance=account["balance"]
            )

    def Withdraw(self, request, context):
        lock = self._get_lock(request.account_id)
        with lock:
            account = load_account(request.account_id)
            if not account:
                return bank_pb2.TransactionResponse(success=False, message="Account not found")
            if account["balance"] < request.amount:
                return bank_pb2.TransactionResponse(success=False, message="Insufficient funds")
            account["balance"] -= request.amount
            account["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_account(request.account_id, account)
            return bank_pb2.TransactionResponse(
                success=True,
                message="Withdrawal successful",
                new_balance=account["balance"]
            )

    def TransferLocal(self, request, context):
        # Bloquea ambas cuentas en orden para evitar deadlocks
        ids = sorted([request.source_account, request.dest_account])
        lock1 = self._get_lock(ids[0])
        lock2 = self._get_lock(ids[1])
        with lock1, lock2:
            src = load_account(request.source_account)
            dst = load_account(request.dest_account)
            if not src or not dst:
                return bank_pb2.TransferResponse(success=False, message="Invalid accounts")
            if src["balance"] < request.amount:
                return bank_pb2.TransferResponse(success=False, message="Insufficient funds")
            src["balance"] -= request.amount
            dst["balance"] += request.amount
            now = datetime.now(timezone.utc).isoformat()
            src["updated_at"] = now
            dst["updated_at"] = now
            save_account(request.source_account, src)
            save_account(request.dest_account, dst)
            tx_id = str(uuid.uuid4())
            return bank_pb2.TransferResponse(
                success=True,
                message="Local transfer successful",
                transaction_id=tx_id
            )

    # ---------- TWO-PHASE COMMIT (REAL) ----------
    def Prepare(self, request, context):
        """Fase 1: Bloquea la cuenta y verifica si la operación es posible."""
        tx_id = request.transaction_id
        acc_id = request.account_id
        amount = request.amount
        op_type = request.operation_type  # "debit" o "credit"

        lock = self._get_lock(acc_id)
        if not lock.acquire(blocking=False):
            # Ya está bloqueada por otra transacción
            return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)

        try:
            account = load_account(acc_id)
            if not account:
                return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)

            # Verificar fondos si es un débito
            if op_type == "debit" and account["balance"] < amount:
                return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)

            # Registrar la transacción pendiente
            self.pending_2pc[tx_id] = {
                "account_id": acc_id,
                "amount": amount,
                "op_type": op_type,
                "lock": lock
            }
            save_pending(tx_id, {
                "account_id": acc_id,
                "amount": amount,
                "op_type": op_type,
                "status": "PREPARED",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=True)

        except Exception as e:
            lock.release()
            return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)

    def Commit(self, request, context):
        """Fase 2: Ejecuta la operación y libera el bloqueo."""
        tx_id = request.transaction_id
        pending = self.pending_2pc.get(tx_id)
        if not pending:
            return bank_pb2.CommitResponse(success=False)

        try:
            account = load_account(pending["account_id"])
            if not account:
                return bank_pb2.CommitResponse(success=False)

            # Aplicar la operación
            if pending["op_type"] == "debit":
                account["balance"] -= pending["amount"]
            elif pending["op_type"] == "credit":
                account["balance"] += pending["amount"]

            account["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_account(pending["account_id"], account)

            # Liberar recursos
            pending["lock"].release()
            del self.pending_2pc[tx_id]
            remove_pending(tx_id)

            return bank_pb2.CommitResponse(success=True)

        except Exception as e:
            # En caso de error, igual liberamos para no dejar bloqueos
            pending["lock"].release()
            del self.pending_2pc[tx_id]
            remove_pending(tx_id)
            return bank_pb2.CommitResponse(success=False)

    def Abort(self, request, context):
        """Libera el bloqueo sin modificar la cuenta."""
        tx_id = request.transaction_id
        pending = self.pending_2pc.get(tx_id)
        if not pending:
            return bank_pb2.AbortResponse(success=True)

        pending["lock"].release()
        del self.pending_2pc[tx_id]
        remove_pending(tx_id)
        return bank_pb2.AbortResponse(success=True)

    # ---------- BULLY (PLACEHOLDER) ----------
    def Heartbeat(self, request, context):
        return bank_pb2.HeartbeatResponse(alive=True, leader_id=self.node_state.get("leader_id", ""))

    def Election(self, request, context):
        return bank_pb2.ElectionResponse(acknowledged=True)

    def Coordinator(self, request, context):
        self.node_state["leader_id"] = request.leader_id
        self.node_state["state"] = "FOLLOWER"
        return bank_pb2.CoordinatorResponse(accepted=True)


# ---------- SERVIDOR ----------
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bank_pb2_grpc.add_BankServiceServicer_to_server(BankService(), server)
    port = "50052"
    server.add_insecure_port(f"[::]:{port}")
    print(f"Banco Chile (gRPC) corriendo en puerto {port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    # Asegurar que exista la carpeta de cuentas
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)
    os.makedirs(PENDING_DIR, exist_ok=True)
    
    if not os.listdir(ACCOUNTS_DIR):
        initial_accounts = [
            {"account_id": "CH001", "owner": "cliente_chile", "balance": 20000.0, "currency": "CLP", "type": "ahorros"},
            {"account_id": "CH002", "owner": "cliente_chile", "balance": 8000.0, "currency": "USD", "type": "corriente"},
            {"account_id": "CH003", "owner": "cliente_compartido", "balance": 5000.0, "currency": "CLP", "type": "ahorros"}
        ]
        for acc in initial_accounts:
            acc["created_at"] = datetime.now(timezone.utc).isoformat()
            acc["updated_at"] = acc["created_at"]
            save_account(acc["account_id"], acc)
        print("Cuentas iniciales creadas.")
    serve()
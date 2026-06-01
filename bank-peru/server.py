import grpc
from concurrent import futures
import bank_pb2
import bank_pb2_grpc
import json
import os
import uuid
from datetime import datetime
import threading
import time

# ---------- CONFIGURACIÓN ----------
NODE_ID = "peru"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")

# ---------- PERSISTENCIA SIMPLE (DFS simulado) ----------
def load_account(account_id):
    """Carga los datos de una cuenta desde JSON."""
    path = os.path.join(ACCOUNTS_DIR, f"{account_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)

def save_account(account_id, data):
    """Guarda los datos de una cuenta en JSON (atómico)."""
    path = os.path.join(ACCOUNTS_DIR, f"{account_id}.json")
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)

# ---------- SERVICIO gRPC ----------
class BankService(bank_pb2_grpc.BankServiceServicer):
    def __init__(self):
        # Estado del nodo
        self.node_state = {
            "node_id": NODE_ID,
            "leader_id": None,
            "state": "FOLLOWER",  # LEADER, FOLLOWER, CANDIDATE
            "last_heartbeat": time.time()
        }
        # Transacciones pendientes para 2PC
        self.pending_2pc = {}
        # Bloqueo simple para concurrencia (en memoria)
        self.locks = {}
        self.lock = threading.Lock()

    # ---------- OPERACIONES BÁSICAS ----------
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
        with self.lock:
            account = load_account(request.account_id)
            if not account:
                return bank_pb2.TransactionResponse(success=False, message="Account not found")
            account["balance"] += request.amount
            account["updated_at"] = datetime.utcnow().isoformat()
            save_account(request.account_id, account)
            return bank_pb2.TransactionResponse(
                success=True,
                message="Deposit successful",
                new_balance=account["balance"]
            )

    def Withdraw(self, request, context):
        with self.lock:
            account = load_account(request.account_id)
            if not account:
                return bank_pb2.TransactionResponse(success=False, message="Account not found")
            if account["balance"] < request.amount:
                return bank_pb2.TransactionResponse(success=False, message="Insufficient funds")
            account["balance"] -= request.amount
            account["updated_at"] = datetime.utcnow().isoformat()
            save_account(request.account_id, account)
            return bank_pb2.TransactionResponse(
                success=True,
                message="Withdrawal successful",
                new_balance=account["balance"]
            )

    def TransferLocal(self, request, context):
        with self.lock:
            src = load_account(request.source_account)
            dst = load_account(request.dest_account)
            if not src or not dst:
                return bank_pb2.TransferResponse(success=False, message="Invalid accounts")
            if src["balance"] < request.amount:
                return bank_pb2.TransferResponse(success=False, message="Insufficient funds")
            # Ejecutar transferencia
            src["balance"] -= request.amount
            dst["balance"] += request.amount
            now = datetime.utcnow().isoformat()
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

    # ---------- 2PC (PLACEHOLDER) ----------
    def Prepare(self, request, context):
        # En la Fase 2 implementaremos el bloqueo de recursos real
        return bank_pb2.PrepareResponse(transaction_id=request.transaction_id, vote=True)

    def Commit(self, request, context):
        # Ejecutar operación pendiente (debit/credit) sobre la cuenta
        return bank_pb2.CommitResponse(success=True)

    def Abort(self, request, context):
        # Liberar bloqueos
        return bank_pb2.AbortResponse(success=True)

    # ---------- BULLY (PLACEHOLDER) ----------
    def Heartbeat(self, request, context):
        return bank_pb2.HeartbeatResponse(alive=True, leader_id=self.node_state.get("leader_id", ""))

    def Election(self, request, context):
        # Si el ID del candidato es menor, este nodo responde y puede iniciar su propia elección
        return bank_pb2.ElectionResponse(acknowledged=True)

    def Coordinator(self, request, context):
        # Recibir mensaje de nuevo líder
        self.node_state["leader_id"] = request.leader_id
        self.node_state["state"] = "FOLLOWER"
        return bank_pb2.CoordinatorResponse(accepted=True)

# ---------- SERVIDOR ----------
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bank_pb2_grpc.add_BankServiceServicer_to_server(BankService(), server)
    port = "50051"
    server.add_insecure_port(f"[::]:{port}")
    print(f"Banco Perú (gRPC) corriendo en puerto {port}")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    # Asegurar que exista la carpeta de cuentas
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)
    # Crear cuentas de ejemplo si no existen
    if not os.listdir(ACCOUNTS_DIR):
        initial_accounts = [
            {"account_id": "PE001", "owner": "cliente_peru", "balance": 15000.0, "currency": "PEN", "type": "ahorros"},
            {"account_id": "PE002", "owner": "cliente_peru", "balance": 5000.0, "currency": "USD", "type": "corriente"},
            {"account_id": "PE003", "owner": "cliente_compartido", "balance": 10000.0, "currency": "PEN", "type": "ahorros"}
        ]
        for acc in initial_accounts:
            acc["created_at"] = datetime.utcnow().isoformat()
            acc["updated_at"] = acc["created_at"]
            save_account(acc["account_id"], acc)
        print("Cuentas iniciales creadas.")
    serve()
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
NODE_ID = "colombia"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")
PENDING_DIR = os.path.join(DATA_DIR, "pending")

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
        # Estado del nodo
        self.node_id = 1  # Colombia: ID 1
        self.leader_id = None
        self.state = "FOLLOWER"  # Se determinará al iniciar

        # Peers (ID -> dirección)
        self.peers = {
            3: "localhost:50051",  # Peru
            2: "localhost:50052"   # Chile
        }

        # Configuración de tiempos
        self.heartbeat_interval = 2       # segundos entre heartbeats
        self.election_timeout = 4         # segundos sin heartbeat del líder antes de iniciar elección
        self.last_heartbeat_from_leader = time.time()

        # Control de concurrencia y elecciones
        self.election_lock = threading.Lock()
        self._election_in_progress = False

        # Bloqueos para 2PC
        self.pending_2pc = {}
        self.account_locks = {}
        self.global_lock = threading.Lock()

        # Iniciar el cluster: esperar un poco y luego determinar el líder inicial
        threading.Thread(target=self._startup, daemon=True).start()

    # ---------- MÉTODOS DE BULLY ----------
    def _startup(self):
        """Espera breve y luego fuerza una elección si no hay líder."""
        time.sleep(1)  # Dar tiempo a que todos los servidores estén listos
        if self.node_id == max(self.peers.keys() | {self.node_id}):
            # Soy el mayor ID, me autoproclamo líder directamente
            self.become_leader()
        else:
            # Inicio elección para descubrir al líder
            self.start_election()

    def _send_heartbeat(self, peer_id, address):
        """Envía heartbeat a un peer."""
        try:
            channel = grpc.insecure_channel(address)
            stub = bank_pb2_grpc.BankServiceStub(channel)
            resp = stub.Heartbeat(bank_pb2.HeartbeatRequest(node_id=str(self.node_id)), timeout=1)
            return resp.alive
        except:
            return False

    def _send_election(self, peer_id, address):
        """Envía mensaje de elección a un peer mayor."""
        try:
            channel = grpc.insecure_channel(address)
            stub = bank_pb2_grpc.BankServiceStub(channel)
            resp = stub.Election(bank_pb2.ElectionRequest(candidate_id=str(self.node_id)), timeout=1)
            return resp.acknowledged
        except:
            return False

    def _send_coordinator(self, peer_id, address):
        """Notifica a un peer que este nodo es el nuevo coordinador."""
        try:
            channel = grpc.insecure_channel(address)
            stub = bank_pb2_grpc.BankServiceStub(channel)
            stub.Coordinator(bank_pb2.CoordinatorRequest(leader_id=str(self.node_id)), timeout=1)
        except:
            pass

    def _heartbeat_loop(self):
        """Envía heartbeats al líder si no somos el líder."""
        while True:
            time.sleep(self.heartbeat_interval)
            if self.state == "FOLLOWER" and self.leader_id is not None:
                leader_addr = self.peers.get(self.leader_id)
                if leader_addr:
                    if not self._send_heartbeat(self.leader_id, leader_addr):
                        print(f"Líder {self.leader_id} no responde a heartbeat")
                        # No forzamos elección aquí; el _election_check_loop lo hará tras el timeout

    def _election_check_loop(self):
        """Monitorea si el líder sigue vivo y dispara elección si es necesario."""
        while True:
            time.sleep(1)
            if self.state == "FOLLOWER" and self.leader_id is not None:
                if time.time() - self.last_heartbeat_from_leader > self.election_timeout:
                    print(f"Tiempo de espera agotado para líder {self.leader_id}. Iniciando elección (nodo {self.node_id})")
                    self.start_election()

    def start_election(self):
        """Inicia el algoritmo Bully."""
        with self.election_lock:
            if self._election_in_progress or self.state == "LEADER":
                return  # Ya hay una elección en curso o ya soy líder
            self._election_in_progress = True

        print(f"Nodo {self.node_id} inicia elección")
        self.state = "CANDIDATE"
        higher_nodes = [nid for nid in self.peers if nid > self.node_id]

        if not higher_nodes:
            # No hay nadie con mayor ID, me proclamo líder directamente
            self.become_leader()
            with self.election_lock:
                self._election_in_progress = False
            return

        # Preguntar a los nodos con mayor ID
        for nid in sorted(higher_nodes, reverse=True):  # Empezar por el más alto
            if self._send_election(nid, self.peers[nid]):
                print(f"Nodo {nid} respondió a mi elección. Esperando su victoria.")
                # Un nodo mayor respondió; él tomará el control
                with self.election_lock:
                    self._election_in_progress = False
                return

        # Nadie respondió, me proclamo líder
        self.become_leader()
        with self.election_lock:
            self._election_in_progress = False

    def become_leader(self):
        """Se proclama coordinador y notifica a todos los peers."""
        self.state = "LEADER"
        self.leader_id = self.node_id
        self.last_heartbeat_from_leader = time.time()  # ¡Importante! Para no reiniciar elección
        print(f"Nodo {self.node_id} se proclama COORDINADOR")
        for nid, addr in self.peers.items():
            if nid != self.node_id:
                self._send_coordinator(nid, addr)

    # ---------- MÉTODOS gRPC (BULLY) ----------
    def Heartbeat(self, request, context):
        # Actualizar el tiempo del último heartbeat si somos seguidores
        if self.state == "FOLLOWER":
            self.last_heartbeat_from_leader = time.time()
        return bank_pb2.HeartbeatResponse(alive=True, leader_id=str(self.leader_id) if self.leader_id else "")

    def Election(self, request, context):
        candidate_id = int(request.candidate_id)
        print(f"Recibido mensaje de elección de nodo {candidate_id}")
        if candidate_id < self.node_id:
            # Un nodo menor quiere iniciar elección; respondemos y tomamos el control
            print(f"Nodo {self.node_id} (mayor) responde a elección de {candidate_id}")
            # Iniciamos nuestra propia elección (si no hay una en curso)
            if not self._election_in_progress:
                self.start_election()
            return bank_pb2.ElectionResponse(acknowledged=True)
        else:
            # El candidato es mayor o igual; no respondemos
            return bank_pb2.ElectionResponse(acknowledged=False)

    def Coordinator(self, request, context):
        new_leader = int(request.leader_id)
        print(f"Nodo {self.node_id} acepta nuevo líder: {new_leader}")
        self.leader_id = new_leader
        self.state = "FOLLOWER"
        self.last_heartbeat_from_leader = time.time()
        with self.election_lock:
            self._election_in_progress = False
        return bank_pb2.CoordinatorResponse(accepted=True)

    # ---------- OPERACIONES BANCARIAS (2PC) ----------
    def _get_lock(self, account_id):
        with self.global_lock:
            if account_id not in self.account_locks:
                self.account_locks[account_id] = threading.Lock()
            return self.account_locks[account_id]

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

    def Prepare(self, request, context):
        tx_id = request.transaction_id
        acc_id = request.account_id
        amount = request.amount
        op_type = request.operation_type

        lock = self._get_lock(acc_id)
        if not lock.acquire(blocking=False):
            return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)

        try:
            account = load_account(acc_id)
            if not account:
                return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)

            if op_type == "debit" and account["balance"] < amount:
                return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)

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
        tx_id = request.transaction_id
        pending = self.pending_2pc.get(tx_id)
        if not pending:
            return bank_pb2.CommitResponse(success=False)

        try:
            account = load_account(pending["account_id"])
            if not account:
                return bank_pb2.CommitResponse(success=False)

            if pending["op_type"] == "debit":
                account["balance"] -= pending["amount"]
            elif pending["op_type"] == "credit":
                account["balance"] += pending["amount"]

            account["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_account(pending["account_id"], account)

            pending["lock"].release()
            del self.pending_2pc[tx_id]
            remove_pending(tx_id)
            return bank_pb2.CommitResponse(success=True)
        except Exception as e:
            pending["lock"].release()
            del self.pending_2pc[tx_id]
            remove_pending(tx_id)
            return bank_pb2.CommitResponse(success=False)

    def Abort(self, request, context):
        tx_id = request.transaction_id
        pending = self.pending_2pc.get(tx_id)
        if not pending:
            return bank_pb2.AbortResponse(success=True)

        pending["lock"].release()
        del self.pending_2pc[tx_id]
        remove_pending(tx_id)
        return bank_pb2.AbortResponse(success=True)


# ---------- SERVIDOR ----------
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service = BankService()
    bank_pb2_grpc.add_BankServiceServicer_to_server(service, server)
    port = "50053"
    server.add_insecure_port(f"[::]:{port}")
    print(f"Banco Colombia (gRPC) corriendo en puerto {port}")
    # Iniciar hilos de Bully **después** de crear el servicio
    threading.Thread(target=service._heartbeat_loop, daemon=True).start()
    threading.Thread(target=service._election_check_loop, daemon=True).start()
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)
    os.makedirs(PENDING_DIR, exist_ok=True)
    if not os.listdir(ACCOUNTS_DIR):
        initial_accounts = [
            {"account_id": "CO001", "owner": "cliente_colombia", "balance": 30000.0, "currency": "COP", "type": "ahorros"},
            {"account_id": "CO002", "owner": "cliente_colombia", "balance": 12000.0, "currency": "USD", "type": "corriente"},
            {"account_id": "CO003", "owner": "cliente_compartido", "balance": 7000.0, "currency": "COP", "type": "ahorros"}
        ]
        for acc in initial_accounts:
            acc["created_at"] = datetime.now(timezone.utc).isoformat()
            acc["updated_at"] = acc["created_at"]
            save_account(acc["account_id"], acc)
        print("Cuentas iniciales creadas.")
    serve()
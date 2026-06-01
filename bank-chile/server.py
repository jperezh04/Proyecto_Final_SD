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

# ── Prometheus ────────────────────────────────────────────────────────────────
from prometheus_client import Counter, Histogram, Gauge, start_http_server

NODE_LABEL = "chile"
METRICS_PORT = 8001

tx_counter = Counter(
    "bank_transactions_total",
    "Total de transacciones procesadas",
    ["node", "type"]          # type: deposit | withdraw | transfer_local | prepare | commit | abort
)
twopc_duration = Histogram(
    "bank_2pc_duration_seconds",
    "Duración de las fases del 2PC",
    ["node", "phase"],        # phase: prepare | commit | abort
    buckets=[.001, .005, .01, .025, .05, .1, .25, .5, 1.0]
)
node_state_gauge = Gauge(
    "bank_node_state",
    "Estado del nodo: 1=LEADER, 0=FOLLOWER, -1=PAUSED",
    ["node"]
)
node_state_gauge.labels(node=NODE_LABEL).set(0)  # arranca como FOLLOWER
# ─────────────────────────────────────────────────────────────────────────────

NODE_ID = "chile"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")
PENDING_DIR = os.path.join(DATA_DIR, "pending")

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


class BankService(bank_pb2_grpc.BankServiceServicer):
    def __init__(self):
        self.node_id = 2
        self.leader_id = None
        self.state = "FOLLOWER"
        self.peers = {3: "localhost:50051", 1: "localhost:50053"}
        self.heartbeat_interval = 3
        self.election_timeout = 6
        self.last_heartbeat_from_leader = time.time()
        self.election_lock = threading.Lock()
        self._election_in_progress = False
        self.pending_2pc = {}
        self.account_locks = {}
        self.global_lock = threading.Lock()
        self.manual_pause = False
        self.event_log = []

        threading.Thread(target=self._startup, daemon=True).start()

    def _log_event(self, type, title, description):
        self.event_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": type,
            "title": title,
            "description": description
        })

    def _update_state_gauge(self):
        if self.manual_pause:
            node_state_gauge.labels(node=NODE_LABEL).set(-1)
        elif self.state == "LEADER":
            node_state_gauge.labels(node=NODE_LABEL).set(1)
        else:
            node_state_gauge.labels(node=NODE_LABEL).set(0)

    def _startup(self):
        time.sleep(1)
        if self.node_id == max(list(self.peers.keys()) + [self.node_id]):
            self.become_leader()
        else:
            self.start_election()

    def _send_heartbeat(self, peer_id, address):
        try:
            channel = grpc.insecure_channel(address)
            stub = bank_pb2_grpc.BankServiceStub(channel)
            resp = stub.Heartbeat(bank_pb2.HeartbeatRequest(node_id=str(self.node_id)), timeout=1)
            return resp.alive
        except Exception:
            return False

    def _send_election(self, peer_id, address):
        try:
            channel = grpc.insecure_channel(address)
            stub = bank_pb2_grpc.BankServiceStub(channel)
            resp = stub.Election(bank_pb2.ElectionRequest(candidate_id=str(self.node_id)), timeout=1)
            return resp.acknowledged
        except Exception:
            return False

    def _send_coordinator(self, peer_id, address):
        try:
            channel = grpc.insecure_channel(address)
            stub = bank_pb2_grpc.BankServiceStub(channel)
            stub.Coordinator(bank_pb2.CoordinatorRequest(leader_id=str(self.node_id)), timeout=1)
        except Exception:
            pass

    def _heartbeat_loop(self):
        while True:
            time.sleep(self.heartbeat_interval)
            if self.manual_pause:
                continue
            if self.state == "LEADER":
                for peer_id, addr in self.peers.items():
                    self._send_heartbeat(peer_id, addr)

    def _election_check_loop(self):
        while True:
            time.sleep(1)
            if self.manual_pause:
                continue
            if self.state == "FOLLOWER":
                if time.time() - self.last_heartbeat_from_leader > self.election_timeout:
                    print(f"[{self.node_id}] Leader timeout. Starting election.")
                    self.start_election()

    def start_election(self):
        with self.election_lock:
            if self._election_in_progress or self.state == "LEADER":
                return
            self._election_in_progress = True
        self.state = "CANDIDATE"
        self._update_state_gauge()
        self._log_event("election", f"Node {self.node_id} started election", "Heartbeat timeout detected")
        print(f"[{self.node_id}] Starting election.")
        higher_nodes = [nid for nid in self.peers if nid > self.node_id]
        if not higher_nodes:
            self.become_leader()
            with self.election_lock:
                self._election_in_progress = False
            return
        for nid in sorted(higher_nodes, reverse=True):
            if self._send_election(nid, self.peers[nid]):
                print(f"[{self.node_id}] Higher node {nid} responded. Waiting for coordinator.")
                with self.election_lock:
                    self._election_in_progress = False
                return
        self.become_leader()
        with self.election_lock:
            self._election_in_progress = False

    def become_leader(self):
        self.state = "LEADER"
        self.leader_id = self.node_id
        self.last_heartbeat_from_leader = time.time()
        self._update_state_gauge()
        self._log_event("election", f"Node {self.node_id} became LEADER", "Coordinator broadcast sent")
        print(f"[{self.node_id}] Became COORDINATOR.")
        for nid, addr in self.peers.items():
            if nid != self.node_id:
                self._send_coordinator(nid, addr)

    # ── gRPC handlers ──────────────────────────────────────────────────────

    def Heartbeat(self, request, context):
        if self.manual_pause:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return bank_pb2.HeartbeatResponse()
        if self.state != "LEADER":
            self.last_heartbeat_from_leader = time.time()
        return bank_pb2.HeartbeatResponse(alive=True, leader_id=str(self.leader_id) if self.leader_id else "")

    def Election(self, request, context):
        if self.manual_pause:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return bank_pb2.ElectionResponse()
        candidate_id = int(request.candidate_id)
        if candidate_id < self.node_id:
            if not self._election_in_progress:
                threading.Thread(target=self.start_election, daemon=True).start()
            return bank_pb2.ElectionResponse(acknowledged=True)
        elif candidate_id > self.node_id:
            # Nodo de mayor prioridad regresó: me rindo
            self.state = "FOLLOWER"
            self.leader_id = None
            with self.election_lock:
                self._election_in_progress = False
            self._update_state_gauge()
            self._log_event("sync",
                            f"Node {self.node_id} defers to Node {candidate_id}",
                            "Higher-priority node re-joined; stepping down")
            print(f"[{self.node_id}] Deferring to higher node {candidate_id}")
            return bank_pb2.ElectionResponse(acknowledged=False)
        else:
            return bank_pb2.ElectionResponse(acknowledged=False)

    def Coordinator(self, request, context):
        if self.manual_pause:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return bank_pb2.CoordinatorResponse()
        new_leader = int(request.leader_id)
        self.leader_id = new_leader
        self.state = "FOLLOWER"
        self.last_heartbeat_from_leader = time.time()
        with self.election_lock:
            self._election_in_progress = False
        self._update_state_gauge()
        self._log_event("sync", f"Accepted new leader: Node {new_leader}", "Coordinator change acknowledged")
        print(f"[{self.node_id}] New leader: {new_leader}")
        return bank_pb2.CoordinatorResponse(accepted=True)

    def GetEvents(self, request, context):
        return bank_pb2.EventsResponse(
            events=[bank_pb2.Event(**e) for e in self.event_log[-30:]]
        )

    def SetNodeStatus(self, request, context):
        self.manual_pause = request.paused
        estado = "paused" if self.manual_pause else "resumed"
        self._update_state_gauge()
        self._log_event("failure" if self.manual_pause else "sync",
                        f"Node {self.node_id} {estado} manually",
                        f"Manual override {'enabled' if self.manual_pause else 'disabled'}")
        print(f"[{self.node_id}] Manual pause: {self.manual_pause}")
        return bank_pb2.NodeStatusResponse(success=True, message=f"Node {self.node_id} {estado}")

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
            tx_counter.labels(node=NODE_LABEL, type="deposit").inc()
            return bank_pb2.TransactionResponse(success=True, message="Deposit successful", new_balance=account["balance"])

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
            tx_counter.labels(node=NODE_LABEL, type="withdraw").inc()
            return bank_pb2.TransactionResponse(success=True, message="Withdrawal successful", new_balance=account["balance"])

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
            tx_counter.labels(node=NODE_LABEL, type="transfer_local").inc()
            return bank_pb2.TransferResponse(success=True, message="Local transfer successful", transaction_id=tx_id)

    def Prepare(self, request, context):
        start = time.time()
        tx_id = request.transaction_id
        acc_id = request.account_id
        amount = request.amount
        op_type = request.operation_type
        lock = self._get_lock(acc_id)
        if not lock.acquire(blocking=False):
            twopc_duration.labels(node=NODE_LABEL, phase="prepare").observe(time.time() - start)
            return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)
        try:
            account = load_account(acc_id)
            if not account:
                lock.release()
                twopc_duration.labels(node=NODE_LABEL, phase="prepare").observe(time.time() - start)
                return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)
            if op_type == "debit" and account["balance"] < amount:
                lock.release()
                twopc_duration.labels(node=NODE_LABEL, phase="prepare").observe(time.time() - start)
                return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)
            self.pending_2pc[tx_id] = {"account_id": acc_id, "amount": amount, "op_type": op_type, "lock": lock}
            save_pending(tx_id, {"account_id": acc_id, "amount": amount, "op_type": op_type,
                                  "status": "PREPARED", "timestamp": datetime.now(timezone.utc).isoformat()})
            tx_counter.labels(node=NODE_LABEL, type="prepare").inc()
            twopc_duration.labels(node=NODE_LABEL, phase="prepare").observe(time.time() - start)
            return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=True)
        except Exception:
            lock.release()
            twopc_duration.labels(node=NODE_LABEL, phase="prepare").observe(time.time() - start)
            return bank_pb2.PrepareResponse(transaction_id=tx_id, vote=False)

    def Commit(self, request, context):
        start = time.time()
        tx_id = request.transaction_id
        pending = self.pending_2pc.get(tx_id)
        if not pending:
            return bank_pb2.CommitResponse(success=False)
        try:
            account = load_account(pending["account_id"])
            if not account:
                pending["lock"].release()
                del self.pending_2pc[tx_id]
                remove_pending(tx_id)
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
            tx_counter.labels(node=NODE_LABEL, type="commit").inc()
            twopc_duration.labels(node=NODE_LABEL, phase="commit").observe(time.time() - start)
            return bank_pb2.CommitResponse(success=True)
        except Exception:
            pending["lock"].release()
            del self.pending_2pc[tx_id]
            remove_pending(tx_id)
            return bank_pb2.CommitResponse(success=False)

    def Abort(self, request, context):
        start = time.time()
        tx_id = request.transaction_id
        pending = self.pending_2pc.get(tx_id)
        if not pending:
            return bank_pb2.AbortResponse(success=True)
        pending["lock"].release()
        del self.pending_2pc[tx_id]
        remove_pending(tx_id)
        tx_counter.labels(node=NODE_LABEL, type="abort").inc()
        twopc_duration.labels(node=NODE_LABEL, phase="abort").observe(time.time() - start)
        return bank_pb2.AbortResponse(success=True)


def serve():
    start_http_server(METRICS_PORT)
    print(f"Métricas Prometheus expuestas en http://localhost:{METRICS_PORT}")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service = BankService()
    bank_pb2_grpc.add_BankServiceServicer_to_server(service, server)
    server.add_insecure_port("[::]:50052")
    print("Banco Chile (gRPC) corriendo en puerto 50052")
    threading.Thread(target=service._heartbeat_loop, daemon=True).start()
    threading.Thread(target=service._election_check_loop, daemon=True).start()
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
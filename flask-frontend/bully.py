import grpc
import bank_pb2
import bank_pb2_grpc
from bank_client import BANKS, get_stub

def get_cluster_state():
    nodes = []
    events = []
    leader_id = None
    bank_ids = {"peru": 3, "chile": 2, "colombia": 1}

    for bank_name, addr in BANKS.items():
        try:
            stub = get_stub(bank_name)
            resp = stub.Heartbeat(bank_pb2.HeartbeatRequest(node_id="status_check"), timeout=1)
            node_id = bank_ids[bank_name]
            if resp.leader_id == str(node_id):
                state = "LEADER"
                leader_id = node_id
            else:
                state = "FOLLOWER"
            nodes.append({
                "name": f"Nodo #{node_id} ({bank_name.capitalize()})",
                "short_name": f"N{node_id}",
                "state": state,
                "priority": node_id,
                "uptime": "en línea",
                "topology_x": "50%" if node_id == 3 else ("20%" if node_id == 2 else "80%"),
                "topology_y": "20%" if node_id == 3 else ("50%" if node_id == 2 else "50%")
            })
        except Exception:
            node_id = bank_ids[bank_name]
            nodes.append({
                "name": f"Nodo #{node_id} ({bank_name.capitalize()})",
                "short_name": f"N{node_id}",
                "state": "DISCONNECTED",
                "priority": node_id,
                "uptime": "-",
                "topology_x": "50%" if node_id == 3 else ("20%" if node_id == 2 else "80%"),
                "topology_y": "20%" if node_id == 3 else ("50%" if node_id == 2 else "50%")
            })

    if leader_id is not None:
        events.append({
            "type": "election",
            "time": "Ahora",
            "title": f"El líder es el Nodo #{leader_id}",
            "description": "Clúster estable con el coordinador actual."
        })
    else:
        events.append({
            "type": "failure",
            "time": "Ahora",
            "title": "No se detectó líder",
            "description": "La elección puede estar en proceso."
        })

    return nodes, events

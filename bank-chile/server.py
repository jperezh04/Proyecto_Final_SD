import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.bank_service import create_and_serve

NODE_CONFIG = {
    "node_label": "chile",
    "node_id": "chile",
    "numeric_id": 2,
    "metrics_port": int(os.getenv("METRICS_PORT", "8001")),
    "grpc_port": 50052,
    "peers": {
        3: os.getenv("BANK_PERU_ADDR", "localhost:50051"),
        1: os.getenv("BANK_COLOMBIA_ADDR", "localhost:50053"),
    },
    "data_dir": os.path.dirname(os.path.abspath(__file__)),
}

if __name__ == "__main__":
    create_and_serve(NODE_CONFIG)

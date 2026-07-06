import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.bank_service import create_and_serve

NODE_CONFIG = {
    "node_label": "peru",
    "node_id": "peru",
    "numeric_id": 3,
    "metrics_port": int(os.getenv("METRICS_PORT", "8000")),
    "grpc_port": 50051,
    "peers": {
        2: os.getenv("BANK_CHILE_ADDR", "localhost:50052"),
        1: os.getenv("BANK_COLOMBIA_ADDR", "localhost:50053"),
    },
    "data_dir": os.path.dirname(os.path.abspath(__file__)),
}

if __name__ == "__main__":
    create_and_serve(NODE_CONFIG)

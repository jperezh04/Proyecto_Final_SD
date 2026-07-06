import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.bank_service import create_and_serve

NODE_CONFIG = {
    "node_label": "colombia",
    "node_id": "colombia",
    "numeric_id": 1,
    "metrics_port": int(os.getenv("METRICS_PORT", "8002")),
    "grpc_port": 50053,
    "peers": {
        3: os.getenv("BANK_PERU_ADDR", "localhost:50051"),
        2: os.getenv("BANK_CHILE_ADDR", "localhost:50052"),
    },
    "data_dir": os.path.dirname(os.path.abspath(__file__)),
}

if __name__ == "__main__":
    create_and_serve(NODE_CONFIG)

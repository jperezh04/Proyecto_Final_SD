import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grpc
import shared.bank_pb2 as bank_pb2
import shared.bank_pb2_grpc as bank_pb2_grpc

BANKS = {
    "peru": "localhost:50051",
    "chile": "localhost:50052",
    "colombia": "localhost:50053"
}

prefixes = {"peru": "PE", "chile": "CH", "colombia": "CO"}

for bank, prefix in prefixes.items():
    stub = bank_pb2_grpc.BankServiceStub(grpc.insecure_channel(BANKS[bank]))
    for i in range(1, 4):
        acc_id = f"{prefix}00{i}"
        try:
            resp = stub.GetBalance(bank_pb2.BalanceRequest(account_id=acc_id))
            print(f"{acc_id}: {resp.balance} {resp.currency}")
        except grpc.RpcError as e:
            print(f"ERROR con {acc_id}: {e.code()} - {e.details()}")

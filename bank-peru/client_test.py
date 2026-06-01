import grpc
import bank_pb2
import bank_pb2_grpc

channel = grpc.insecure_channel("localhost:50051")
stub = bank_pb2_grpc.BankServiceStub(channel)

# Probar saldo
resp = stub.GetBalance(bank_pb2.BalanceRequest(account_id="PE001"))
print(f"Saldo PE001: {resp.balance} {resp.currency}")

# Probar depósito
resp = stub.Deposit(bank_pb2.TransactionRequest(account_id="PE001", amount=500))
print(f"Depósito: {resp.message}, nuevo saldo: {resp.new_balance}")

# Probar transferencia local
resp = stub.TransferLocal(bank_pb2.TransferRequest(
    source_account="PE001",
    dest_account="PE002",
    amount=200,
    description="Prueba"
))
print(f"Transferencia: {resp.message}, ID: {resp.transaction_id}")
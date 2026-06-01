import grpc
import bank_pb2
import bank_pb2_grpc

BANKS = {
    "peru": "localhost:50051",
    "chile": "localhost:50052",
    "colombia": "localhost:50053"
}

def get_stub(bank):
    if bank not in BANKS:
        raise ValueError(f"Banco {bank} no encontrado")
    channel = grpc.insecure_channel(BANKS[bank])
    return bank_pb2_grpc.BankServiceStub(channel)

def get_all_accounts_for_user(user_id):
    """Obtiene todas las cuentas de todos los bancos para un usuario."""
    accounts = []
    # Mapeo de prefijos según el banco
    prefixes = {"peru": "PE", "chile": "CH", "colombia": "CO"}
    for bank, prefix in prefixes.items():
        stub = get_stub(bank)
        for i in range(1, 4):  # Asumimos 3 cuentas por banco
            acc_id = f"{prefix}00{i}"
            try:
                resp = stub.GetBalance(bank_pb2.BalanceRequest(account_id=acc_id))
                accounts.append({
                    'number': acc_id,
                    'description': f'Cuenta {i}',
                    'bank': f'Banco {bank.capitalize()}',
                    'country': bank.capitalize(),
                    'country_code': bank[:2],
                    'type': 'Ahorros' if i != 2 else 'Corriente',
                    'balance': f"${resp.balance:,.2f}",
                    'currency': resp.currency,
                    'status': 'active'
                })
            except Exception as e:
                print(f"Error obteniendo {acc_id}: {e}")
    return accounts
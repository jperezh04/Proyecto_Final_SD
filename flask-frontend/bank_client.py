import logging
import os
import grpc
import bank_pb2
import bank_pb2_grpc

logger = logging.getLogger("flask-frontend.bank_client")

BANKS = {
    "peru": os.getenv("BANK_PERU_ADDR", "localhost:50051"),
    "chile": os.getenv("BANK_CHILE_ADDR", "localhost:50052"),
    "colombia": os.getenv("BANK_COLOMBIA_ADDR", "localhost:50053"),
}

BANK_LABELS = {
    "peru": "Global Finance (Perú)",
    "chile": "Banco Chile",
    "colombia": "Banco Colombia",
}

BANK_PREFIXES = {
    "peru": "PE",
    "chile": "CH",
    "colombia": "CO",
}


def get_stub(bank):
    if bank not in BANKS:
        raise ValueError(f"Banco {bank} no encontrado")
    channel = grpc.insecure_channel(BANKS[bank])
    return bank_pb2_grpc.BankServiceStub(channel)


def bank_from_account(account_id):
    account_id = (account_id or "").upper()
    for bank, prefix in BANK_PREFIXES.items():
        if account_id.startswith(prefix):
            return bank
    return None


def _account_to_dict(bank, account):
    account_type = account.type.capitalize() if account.type else "Cuenta"
    return {
        "number": account.account_id,
        "description": account_type,
        "bank": BANK_LABELS.get(bank, bank.capitalize()),
        "bank_id": bank,
        "country": bank.capitalize(),
        "country_code": bank[:2].upper(),
        "type": account_type,
        "owner": account.owner,
        "numeric_balance": float(account.balance),
        "balance": f"{account.currency} {account.balance:,.2f}",
        "currency": account.currency,
        "status": "active",
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def get_accounts_by_bank(owner=""):
    """Consulta las cuentas reales expuestas por cada nodo gRPC."""
    grouped = {bank: [] for bank in BANKS}
    for bank in BANKS:
        try:
            stub = get_stub(bank)
            resp = stub.ListAccounts(bank_pb2.AccountsRequest(owner=owner or ""), timeout=2)
            grouped[bank] = [_account_to_dict(bank, account) for account in resp.accounts]
        except grpc.RpcError as e:
            logger.warning("Error obteniendo cuentas de %s: %s", bank, e.code().name)
            grouped[bank] = []
        except Exception:
            logger.exception("Error inesperado obteniendo cuentas de %s", bank)
            grouped[bank] = []
    return grouped


def get_all_accounts_for_user(user_id=None):
    """Obtiene cuentas reales desde todos los bancos.

    - Admin / vacío: devuelve todas las cuentas para monitoreo y demo general.
    - Cliente: filtra por owner, simulando acceso real del usuario a sus cuentas.
    """
    owner = (user_id or "").strip()
    accounts = []
    for bank_accounts in get_accounts_by_bank(owner=owner).values():
        accounts.extend(bank_accounts)
    return accounts


def _tx_to_dict(tx):
    bank_id = tx.bank_id or bank_from_account(tx.source_account) or bank_from_account(tx.dest_account) or "desconocido"
    return {
        "transaction_id": tx.transaction_id,
        "timestamp": tx.timestamp,
        "type": tx.type,
        "source_account": tx.source_account,
        "dest_account": tx.dest_account,
        "amount": float(tx.amount),
        "currency": tx.currency,
        "description": tx.description,
        "status": tx.status,
        "bank_id": bank_id,
        "bank_label": BANK_LABELS.get(bank_id, bank_id.capitalize()),
    }


def get_all_transactions(account_id=""):
    """Recupera movimientos reales registrados por los nodos y une las dos fases del 2PC."""
    raw = []
    for bank in BANKS:
        try:
            stub = get_stub(bank)
            resp = stub.GetTransactions(bank_pb2.TransactionsRequest(account_id=account_id or ""), timeout=2)
            raw.extend(_tx_to_dict(tx) for tx in resp.transactions)
        except grpc.RpcError as e:
            logger.warning("Error obteniendo movimientos de %s: %s", bank, e.code().name)
        except Exception:
            logger.exception("Error inesperado obteniendo movimientos de %s", bank)

    grouped = {}
    standalone = []
    for tx in raw:
        if tx["type"] in ("2pc_debit", "2pc_credit"):
            grouped.setdefault(tx["transaction_id"], []).append(tx)
        else:
            standalone.append(tx)

    combined = []
    for tx_id, parts in grouped.items():
        debit = next((p for p in parts if p["type"] == "2pc_debit"), None)
        credit = next((p for p in parts if p["type"] == "2pc_credit"), None)
        base = debit or credit or parts[0]
        combined.append({
            "transaction_id": tx_id,
            "timestamp": max(p["timestamp"] for p in parts if p.get("timestamp")),
            "type": "Transferencia interbancaria",
            "source_account": debit["source_account"] if debit else "—",
            "dest_account": credit["dest_account"] if credit else "—",
            "source_bank": BANK_LABELS.get(debit["bank_id"], debit["bank_id"].capitalize()) if debit else "—",
            "dest_bank": BANK_LABELS.get(credit["bank_id"], credit["bank_id"].capitalize()) if credit else "—",
            "amount": base["amount"],
            "currency": base["currency"],
            "description": base["description"],
            "status": "exitosa" if debit and credit else "parcial",
        })

    for tx in standalone:
        tx_type = {
            "transfer_local": "Transferencia local",
            "deposit": "Depósito",
            "withdraw": "Retiro",
        }.get(tx["type"], tx["type"].replace("_", " ").title())
        combined.append({
            "transaction_id": tx["transaction_id"],
            "timestamp": tx["timestamp"],
            "type": tx_type,
            "source_account": tx["source_account"] or "—",
            "dest_account": tx["dest_account"] or "—",
            "source_bank": tx["bank_label"],
            "dest_bank": tx["bank_label"],
            "amount": tx["amount"],
            "currency": tx["currency"],
            "description": tx["description"],
            "status": {"successful": "exitosa", "success": "exitosa", "failed": "fallida"}.get(tx["status"], tx["status"]),
        })

    combined.sort(key=lambda tx: tx.get("timestamp", ""), reverse=True)
    return combined

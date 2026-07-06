import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grpc
import uuid
import shared.bank_pb2 as bank_pb2
from shared.exchange import convert_amount
from bank_client import get_stub


def _get_balance_snapshot(stub, account_id):
    response = stub.GetBalance(bank_pb2.BalanceRequest(account_id=account_id), timeout=5)
    return {
        "account_id": response.account_id,
        "balance": float(response.balance),
        "currency": response.currency,
    }


def execute_interbank_transfer(source_bank, source_account, dest_bank, dest_account, amount, description=""):
    """
    Ejecuta una transferencia interbancaria usando 2PC.

    El monto recibido se interpreta en la moneda de la cuenta origen.
    Si la cuenta destino usa otra moneda, se acredita el monto convertido con
    el tipo de cambio interno del sistema.

    Retorna: (success: bool, message: str, tx_id: str, conversion: dict)
    """
    tx_id = str(uuid.uuid4())
    empty_conversion = {
        "source_amount": round(float(amount or 0), 2),
        "source_currency": "",
        "destination_amount": round(float(amount or 0), 2),
        "destination_currency": "",
        "exchange_rate": 1.0,
        "conversion_applied": False,
    }

    if amount <= 0:
        return False, "El monto debe ser mayor que cero", tx_id, empty_conversion
    if source_bank == dest_bank or source_account == dest_account:
        return False, "La transferencia interbancaria requiere bancos y cuentas distintas", tx_id, empty_conversion

    print(f"\nIniciando 2PC {tx_id}: {source_account} ({source_bank}) -> {dest_account} ({dest_bank}) por {amount}")

    # 1. Obtener stubs de ambos bancos
    try:
        src_stub = get_stub(source_bank)
        dst_stub = get_stub(dest_bank)
        source_snapshot = _get_balance_snapshot(src_stub, source_account)
        dest_snapshot = _get_balance_snapshot(dst_stub, dest_account)
        destination_amount, exchange_rate = convert_amount(
            amount,
            source_snapshot["currency"],
            dest_snapshot["currency"],
        )
        conversion = {
            "source_amount": round(float(amount), 2),
            "source_currency": source_snapshot["currency"],
            "destination_amount": destination_amount,
            "destination_currency": dest_snapshot["currency"],
            "exchange_rate": exchange_rate,
            "conversion_applied": source_snapshot["currency"] != dest_snapshot["currency"],
        }
    except Exception as e:
        return False, f"Error conectando a los bancos o calculando conversión: {e}", tx_id, empty_conversion

    # 2. Fase PREPARE
    print("Enviando PREPARE...")
    src_prep = None
    dst_prep = None
    try:
        src_prep = src_stub.Prepare(bank_pb2.PrepareRequest(
            transaction_id=tx_id,
            account_id=source_account,
            amount=amount,
            operation_type="debit"
        ), timeout=5)
        dst_prep = dst_stub.Prepare(bank_pb2.PrepareRequest(
            transaction_id=tx_id,
            account_id=dest_account,
            amount=destination_amount,
            operation_type="credit"
        ), timeout=5)
    except grpc.RpcError as e:
        print(f"Error en PREPARE: {e.code()}")
        if src_prep is not None and src_prep.vote:
            try:
                src_stub.Abort(bank_pb2.AbortRequest(transaction_id=tx_id))
            except Exception:
                pass
        if dst_prep is not None and dst_prep.vote:
            try:
                dst_stub.Abort(bank_pb2.AbortRequest(transaction_id=tx_id))
            except Exception:
                pass
        return False, f"Falló la fase de preparación: {e.code()}", tx_id, conversion

    # 3. Verificar votos
    if not (src_prep.vote and dst_prep.vote):
        print("Uno de los bancos votó ABORT")
        try:
            src_stub.Abort(bank_pb2.AbortRequest(transaction_id=tx_id))
        except Exception:
            pass
        try:
            dst_stub.Abort(bank_pb2.AbortRequest(transaction_id=tx_id))
        except Exception:
            pass
        return False, "Transacción abortada por uno de los bancos", tx_id, conversion

    # 4. Fase COMMIT
    print("Todos votaron PREPARED, enviando COMMIT...")
    try:
        src_commit = src_stub.Commit(bank_pb2.CommitRequest(transaction_id=tx_id), timeout=5)
        dst_commit = dst_stub.Commit(bank_pb2.CommitRequest(transaction_id=tx_id), timeout=5)
        if src_commit.success and dst_commit.success:
            print(f"Transacción {tx_id} completada exitosamente")
            if conversion["conversion_applied"]:
                msg = (
                    "Transferencia completada con conversión: "
                    f"{conversion['source_amount']:,.2f} {conversion['source_currency']} -> "
                    f"{conversion['destination_amount']:,.2f} {conversion['destination_currency']}"
                )
            else:
                msg = "Transferencia completada correctamente"
            return True, msg, tx_id, conversion
        return False, "Fallo en la fase de confirmación", tx_id, conversion
    except Exception as e:
        print(f"Error en COMMIT: {e}")
        return False, f"Error al confirmar la transacción: {e}", tx_id, conversion

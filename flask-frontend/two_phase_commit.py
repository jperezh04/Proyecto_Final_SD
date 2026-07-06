import logging
import grpc
import uuid
import bank_pb2
from bank_client import get_stub

logger = logging.getLogger("flask-frontend.two_phase_commit")

# Tipo de cambio interno del sistema.
# Base: 1 USD = X moneda local. Es fijo para que el entorno sea reproducible.
EXCHANGE_RATES = {
    "USD": 1.0,
    "PEN": 3.75,
    "CLP": 950.0,
    "COP": 4000.0,
}


def convert_amount(amount, source_currency, dest_currency):
    source_currency = (source_currency or "").upper()
    dest_currency = (dest_currency or "").upper()
    if source_currency == dest_currency:
        return round(float(amount), 2), 1.0
    if source_currency not in EXCHANGE_RATES or dest_currency not in EXCHANGE_RATES:
        raise ValueError(f"Moneda no soportada: {source_currency} -> {dest_currency}")
    usd_amount = float(amount) / EXCHANGE_RATES[source_currency]
    converted = usd_amount * EXCHANGE_RATES[dest_currency]
    exchange_rate = EXCHANGE_RATES[dest_currency] / EXCHANGE_RATES[source_currency]
    return round(converted, 2), round(exchange_rate, 6)


def _safe_abort(stub, tx_id, bank):
    """Intenta abortar la transacción en un banco, registrando cualquier fallo.

    Un abort fallido deja un bloqueo/reserva colgada en el nodo, así que no debe
    tragarse en silencio.
    """
    try:
        stub.Abort(bank_pb2.AbortRequest(transaction_id=tx_id))
        return True
    except grpc.RpcError as e:
        logger.error("No se pudo abortar %s en %s: %s", tx_id, bank, e.code().name)
        return False
    except Exception:
        logger.exception("Error inesperado abortando %s en %s", tx_id, bank)
        return False


def _try_commit(stub, tx_id, bank):
    """Confirma la transacción en un banco. Devuelve True solo si el banco confirmó."""
    try:
        resp = stub.Commit(bank_pb2.CommitRequest(transaction_id=tx_id), timeout=5)
        if not resp.success:
            logger.error("El banco %s no confirmó %s (success=False)", bank, tx_id)
        return resp.success
    except grpc.RpcError as e:
        logger.error("Fallo RPC confirmando %s en %s: %s", tx_id, bank, e.code().name)
        return False
    except Exception:
        logger.exception("Error inesperado confirmando %s en %s", tx_id, bank)
        return False


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

    logger.info("Iniciando 2PC %s: %s (%s) -> %s (%s) por %s",
                tx_id, source_account, source_bank, dest_account, dest_bank, amount)

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
    except grpc.RpcError as e:
        logger.warning("2PC %s: error conectando a los bancos: %s", tx_id, e.code().name)
        return False, f"Error conectando a los bancos: {e.code().name}", tx_id, empty_conversion
    except ValueError as e:
        logger.warning("2PC %s: conversión inválida: %s", tx_id, e)
        return False, str(e), tx_id, empty_conversion
    except Exception as e:
        logger.exception("2PC %s: error inesperado preparando la transferencia", tx_id)
        return False, f"Error conectando a los bancos o calculando conversión: {e}", tx_id, empty_conversion

    # 2. Fase PREPARE
    logger.info("2PC %s: enviando PREPARE", tx_id)
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
        logger.warning("2PC %s: error en PREPARE: %s", tx_id, e.code().name)
        # Solo hay que abortar los nodos que ya reservaron (votaron sí).
        if src_prep is not None and src_prep.vote:
            _safe_abort(src_stub, tx_id, source_bank)
        if dst_prep is not None and dst_prep.vote:
            _safe_abort(dst_stub, tx_id, dest_bank)
        return False, f"Falló la fase de preparación: {e.code().name}", tx_id, conversion

    # 3. Verificar votos
    if not (src_prep.vote and dst_prep.vote):
        logger.info("2PC %s: uno de los bancos votó ABORT (src=%s, dst=%s)",
                    tx_id, src_prep.vote, dst_prep.vote)
        _safe_abort(src_stub, tx_id, source_bank)
        _safe_abort(dst_stub, tx_id, dest_bank)
        return False, "Transacción abortada por uno de los bancos", tx_id, conversion

    # 4. Fase COMMIT
    # Tras un voto unánime, el commit debe aplicarse en ambos nodos. Si solo uno
    # confirma, el sistema queda inconsistente: hay que detectarlo y reportarlo,
    # no tragarse el error.
    logger.info("2PC %s: todos votaron PREPARED, enviando COMMIT", tx_id)
    src_committed = _try_commit(src_stub, tx_id, source_bank)
    dst_committed = _try_commit(dst_stub, tx_id, dest_bank)

    if src_committed and dst_committed:
        logger.info("2PC %s completada exitosamente", tx_id)
        if conversion["conversion_applied"]:
            msg = (
                "Transferencia completada con conversión: "
                f"{conversion['source_amount']:,.2f} {conversion['source_currency']} -> "
                f"{conversion['destination_amount']:,.2f} {conversion['destination_currency']}"
            )
        else:
            msg = "Transferencia completada correctamente"
        return True, msg, tx_id, conversion

    if src_committed != dst_committed:
        committed_bank = source_bank if src_committed else dest_bank
        pending_bank = dest_bank if src_committed else source_bank
        logger.critical(
            "2PC %s INCONSISTENTE: %s confirmó pero %s no. Requiere reconciliación manual.",
            tx_id, committed_bank, pending_bank)
        return False, (
            f"Transacción en estado inconsistente (ID {tx_id}): {committed_bank} "
            f"confirmó pero {pending_bank} no. Se requiere reconciliación manual."
        ), tx_id, conversion

    logger.error("2PC %s: ningún banco confirmó en la fase de commit", tx_id)
    return False, "Fallo en la fase de confirmación", tx_id, conversion

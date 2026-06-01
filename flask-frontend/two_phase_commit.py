import grpc
import uuid
import bank_pb2
import bank_pb2_grpc
from bank_client import BANKS, get_stub

def execute_interbank_transfer(source_bank, source_account, dest_bank, dest_account, amount):
    """
    Ejecuta una transferencia interbancaria usando 2PC.
    Retorna (success: bool, message: str, tx_id: str)
    """
    tx_id = str(uuid.uuid4())
    print(f"\n🔁 Iniciando 2PC {tx_id}: {source_account} ({source_bank}) → {dest_account} ({dest_bank}) por {amount}")

    # 1. Obtener stubs de ambos bancos
    try:
        src_stub = get_stub(source_bank)
        dst_stub = get_stub(dest_bank)
    except Exception as e:
        return False, f"Error conectando a los bancos: {e}", tx_id

    # 2. Fase PREPARE
    print("📤 Enviando PREPARE...")
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
            amount=amount,
            operation_type="credit"
        ), timeout=5)
    except grpc.RpcError as e:
        print(f"❌ Error en PREPARE: {e.code()}")
        # Si uno falla, abortamos el otro
        if 'src_prep' in locals() and src_prep.vote:
            src_stub.Abort(bank_pb2.AbortRequest(transaction_id=tx_id))
        return False, f"Prepare falló: {e.code()}", tx_id

    # 3. Verificar votos
    if not (src_prep.vote and dst_prep.vote):
        print("❌ Uno de los bancos votó ABORT")
        src_stub.Abort(bank_pb2.AbortRequest(transaction_id=tx_id))
        dst_stub.Abort(bank_pb2.AbortRequest(transaction_id=tx_id))
        return False, "Transacción abortada por uno de los bancos", tx_id

    # 4. Fase COMMIT
    print("✅ Todos votaron PREPARED, enviando COMMIT...")
    try:
        src_commit = src_stub.Commit(bank_pb2.CommitRequest(transaction_id=tx_id), timeout=5)
        dst_commit = dst_stub.Commit(bank_pb2.CommitRequest(transaction_id=tx_id), timeout=5)
        if src_commit.success and dst_commit.success:
            print(f"✅ Transacción {tx_id} completada exitosamente")
            return True, "Transferencia completada con éxito", tx_id
        else:
            # Esto no debería pasar si el prepare fue exitoso, pero por seguridad
            return False, "Fallo en la fase de commit", tx_id
    except Exception as e:
        print(f"❌ Error en COMMIT: {e}")
        return False, f"Error en commit: {e}", tx_id
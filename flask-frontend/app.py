import logging
import os
import time
import grpc
from datetime import datetime, timezone

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from dotenv import load_dotenv

from bank_client import (
    get_all_accounts_for_user, get_accounts_by_bank, get_all_transactions,
    get_stub, BANKS, BANK_LABELS, BANK_PREFIXES, bank_from_account
)
import bank_pb2
import bank_pb2_grpc
from two_phase_commit import execute_interbank_transfer
from bully import get_cluster_state
import requests as http_requests

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("flask-frontend")

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'clave-por-defecto')

transactions_today_count = 0
manual_pause_state = {bank: False for bank in BANKS}
local_event_log = []

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

# Tipo de cambio interno del sistema.
# Base: 1 USD = X moneda local. Fijo para que el entorno sea reproducible.
EXCHANGE_RATES = {
    "USD": 1.0,
    "PEN": 3.75,
    "CLP": 950.0,
    "COP": 4000.0,
}

# Usuarios de prueba para acceso de clientes.
# En una versión con BD, esto pasaría a una tabla de usuarios con hash de contraseña.
CLIENT_CREDENTIALS = {
    "ana_peru_solo": {"password": "123456", "name": "Ana Torres"},
    "bruno_chile_solo": {"password": "123456", "name": "Bruno Fernández"},
    "camila_colombia_solo": {"password": "123456", "name": "Camila Rojas"},
    "diego_peru_chile": {"password": "123456", "name": "Diego Salazar"},
    "valeria_global": {"password": "123456", "name": "Valeria Global"},
    "esteban_colombia_solo": {"password": "123456", "name": "Esteban Mora"},
}

def _convert_amount(amount, source_currency, dest_currency):
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

def _get_account_snapshot(bank, account_id):
    stub = get_stub(bank)
    resp = stub.GetBalance(bank_pb2.BalanceRequest(account_id=account_id), timeout=2)
    return {
        "account_id": resp.account_id,
        "balance": float(resp.balance),
        "currency": resp.currency,
    }

def _conversion_details(amount, source_bank, source_account, dest_bank, dest_account):
    source = _get_account_snapshot(source_bank, source_account)
    dest = _get_account_snapshot(dest_bank, dest_account)
    dest_amount, exchange_rate = _convert_amount(amount, source["currency"], dest["currency"])
    return {
        "source_amount": round(float(amount), 2),
        "source_currency": source["currency"],
        "destination_amount": dest_amount,
        "destination_currency": dest["currency"],
        "exchange_rate": exchange_rate,
        "conversion_applied": source["currency"] != dest["currency"],
    }


def _log_local_event(etype, title, description):
    local_event_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": etype,
        "title": title,
        "description": description
    })
    if len(local_event_log) > 100:
        local_event_log.pop(0)

def _is_client_session():
    return session.get('user_type') == 'client' and bool(session.get('client_owner'))

def _session_owner_filter():
    """Devuelve el owner que debe usarse para filtrar cuentas. Admin ve todo."""
    return session.get('client_owner', '') if _is_client_session() else ''

def _get_visible_accounts():
    return get_all_accounts_for_user(_session_owner_filter())

def _account_belongs_to_session(account_id):
    if not _is_client_session():
        return True
    owner = session.get('client_owner')
    account_id = (account_id or '').strip().upper()
    return any(acc.get('number') == account_id and acc.get('owner') == owner for acc in _get_visible_accounts())

def _filter_transactions_for_session(transactions):
    if not _is_client_session():
        return transactions
    visible_account_ids = {acc.get('number') for acc in _get_visible_accounts()}
    return [
        tx for tx in transactions
        if tx.get('source_account') in visible_account_ids or tx.get('dest_account') in visible_account_ids
    ]

def _redirect_clients_to_transfers():
    if _is_client_session():
        return redirect(url_for('transfers'))
    return None


def _client_forbidden_json():
    if _is_client_session():
        return jsonify({'success': False, 'message': 'Esta sección es solo para el panel institucional'}), 403
    return None


def _decorate_account_for_transfer(acc):
    owner = acc.get('owner', '—')
    return {
        'number': acc['number'],
        'owner': owner,
        'owner_label': _client_display_name(owner),
        'type': acc.get('type', 'Cuenta'),
        'bank': acc['bank'],
        'bank_id': acc['bank_id'],
        'currency': acc['currency'],
        'numeric_balance': acc.get('numeric_balance', 0),
        'balance': acc['balance']
    }

def get_user():
    if _is_client_session():
        owner = session.get('client_owner')
        name = session.get('client_name') or CLIENT_CREDENTIALS.get(owner, {}).get('name', owner)
        return {
            'name': name,
            'bank_name': 'Banca digital',
            'role': f'Cliente · {owner}',
            'user_type': 'client',
            'client_owner': owner,
            'avatar_url': f'https://ui-avatars.com/api/?name={name.replace(" ", "+")}&background=10b981&color=fff'
        }
    return {
        'name': session.get('user', 'Admin'),
        'bank_name': 'Global Finance',
        'role': 'Panel institucional',
        'user_type': 'admin',
        'avatar_url': 'https://ui-avatars.com/api/?name=Admin&background=316bf3&color=fff'
    }

def check_bank_health():
    healthy = 0
    total_latency = 0
    for bank in BANKS:
        start = time.time()
        try:
            stub = get_stub(bank)
            stub.ListAccounts(bank_pb2.AccountsRequest(owner=""), timeout=2)
            latency = (time.time() - start) * 1000
            healthy += 1
            total_latency += latency
        except grpc.RpcError as exc:
            logger.warning("Health check falló para banco %s: %s", bank, exc.code().name)
        except Exception:
            logger.exception("Error inesperado en health check del banco %s", bank)
    avg_latency = round(total_latency / healthy) if healthy > 0 else 0
    return healthy, avg_latency

def get_balance_distribution(accounts):
    distribution = {bank: 0 for bank in BANKS}
    for acc in accounts:
        bank = acc.get('bank_id') or bank_from_account(acc.get('number'))
        if bank in distribution:
            distribution[bank] += float(acc.get('numeric_balance', 0))
    max_balance = max(distribution.values()) if distribution else 1
    heights = [int((v / max_balance) * 100) if max_balance > 0 else 0 for v in distribution.values()]
    return heights

def _format_money(currency, amount):
    return f"{currency} {amount:,.2f}"


def _client_display_name(owner):
    """Convierte el owner técnico del JSON en un nombre legible para la vista."""
    owner = owner or "cliente_sin_nombre"
    custom_names = {
        "ana_peru_solo": "Ana Torres",
        "bruno_chile_solo": "Bruno Fernández",
        "camila_colombia_solo": "Camila Rojas",
        "diego_peru_chile": "Diego Salazar",
        "valeria_global": "Valeria Global",
        "esteban_colombia_solo": "Esteban Mora",
    }
    if owner in custom_names:
        return custom_names[owner]
    return owner.replace("_", " ").title()


def _client_segment(bank_count):
    if bank_count >= 3:
        return "Cliente global"
    if bank_count == 2:
        return "Cliente binacional"
    return "Cliente local"


def _currency_totals(accounts):
    totals = {}
    for acc in accounts:
        currency = acc.get("currency", "") or "—"
        totals[currency] = totals.get(currency, 0) + float(acc.get("numeric_balance", 0))
    return [
        {"currency": currency, "amount": amount, "formatted": _format_money(currency, amount)}
        for currency, amount in sorted(totals.items())
    ]


def _estimated_usd(accounts):
    total = 0.0
    for acc in accounts:
        currency = (acc.get("currency") or "USD").upper()
        rate = EXCHANGE_RATES.get(currency)
        if rate:
            total += float(acc.get("numeric_balance", 0)) / rate
    return round(total, 2)


def _build_clients_summary(accounts):
    """Agrupa las cuentas reales por cliente para demostrar los requisitos del proyecto."""
    grouped = {}
    bank_owners = {bank: set() for bank in BANKS}

    for acc in accounts:
        owner = acc.get("owner") or "cliente_sin_nombre"
        bank_id = acc.get("bank_id") or bank_from_account(acc.get("number")) or "desconocido"
        bank_owners.setdefault(bank_id, set()).add(owner)
        grouped.setdefault(owner, []).append(acc)

    clients = []
    exclusive_by_bank = {bank: False for bank in BANKS}

    for owner, client_accounts in sorted(grouped.items()):
        bank_ids = sorted({acc.get("bank_id") or bank_from_account(acc.get("number")) for acc in client_accounts})
        bank_ids = [bank for bank in bank_ids if bank]
        bank_count = len(bank_ids)
        if bank_count == 1 and bank_ids[0] in exclusive_by_bank:
            exclusive_by_bank[bank_ids[0]] = True

        clients.append({
            "owner": owner,
            "name": _client_display_name(owner),
            "segment": _client_segment(bank_count),
            "bank_count": bank_count,
            "banks": [BANK_LABELS.get(bank, bank.capitalize()) for bank in bank_ids],
            "bank_ids": bank_ids,
            "accounts_count": len(client_accounts),
            "accounts": sorted(client_accounts, key=lambda a: a.get("number", "")),
            "currency_totals": _currency_totals(client_accounts),
            "estimated_usd": _estimated_usd(client_accounts),
            "meets_min_accounts": len(client_accounts) >= 3,
        })

    requirement_status = {
        "bank_min_clients": all(len(owners) >= 3 for owners in bank_owners.values()),
        "client_min_accounts": all(client["accounts_count"] >= 3 for client in clients) if clients else False,
        "exclusive_client_each_bank": all(exclusive_by_bank.values()) if exclusive_by_bank else False,
        "client_two_banks": any(client["bank_count"] == 2 for client in clients),
        "client_three_banks": any(client["bank_count"] >= 3 for client in clients),
    }

    stats = {
        "total_clients": len(clients),
        "total_accounts": len(accounts),
        "exclusive_clients": sum(1 for client in clients if client["bank_count"] == 1),
        "multibank_clients": sum(1 for client in clients if client["bank_count"] >= 2),
        "global_clients": sum(1 for client in clients if client["bank_count"] >= 3),
        "bank_clients": {BANK_LABELS.get(bank, bank.capitalize()): len(owners) for bank, owners in bank_owners.items()},
        "requirements_ok": all(requirement_status.values()) if requirement_status else False,
    }
    return clients, stats, requirement_status

def _account_exists_in_bank(bank, account_id):
    """Indica si la cuenta existe en el banco.

    Solo un NOT_FOUND explícito significa "no existe". Cualquier otro error RPC
    (banco caído, timeout) se propaga para no confundir una caída del servicio
    con una cuenta inexistente.
    """
    try:
        _get_account_snapshot(bank, account_id)
        return True
    except grpc.RpcError as exc:
        if exc.code() == grpc.StatusCode.NOT_FOUND:
            return False
        raise

def _validate_transfer_payload(data):
    required = ["source_bank", "source_account", "dest_bank", "dest_account", "amount"]
    missing = [field for field in required if field not in data or data.get(field) is None or data.get(field) == ""]
    if missing:
        return None, f"Faltan campos: {', '.join(missing)}", 400

    source_bank = data["source_bank"]
    dest_bank = data["dest_bank"]
    source_account = data["source_account"].strip().upper()
    dest_account = data["dest_account"].strip().upper()

    if source_bank not in BANKS or dest_bank not in BANKS:
        return None, "Banco seleccionado inválido", 400

    try:
        amount = float(data["amount"])
    except (TypeError, ValueError):
        return None, "El monto debe ser numérico", 400

    if amount <= 0:
        return None, "El monto debe ser mayor que cero", 400

    if source_account == dest_account:
        return None, "La cuenta origen y destino deben ser distintas", 400

    if bank_from_account(source_account) != source_bank:
        return None, "La cuenta origen no pertenece al banco seleccionado", 400

    if bank_from_account(dest_account) != dest_bank:
        return None, "La cuenta destino no pertenece al banco seleccionado", 400

    try:
        if not _account_exists_in_bank(source_bank, source_account):
            return None, "Cuenta origen no encontrada", 400
        if not _account_exists_in_bank(dest_bank, dest_account):
            return None, "Cuenta destino no encontrada", 400
    except grpc.RpcError as exc:
        logger.warning("No se pudo validar cuentas por error de servicio: %s", exc.code().name)
        return None, f"Servicio bancario no disponible: {exc.code().name}", 503

    return {
        "source_bank": source_bank,
        "source_account": source_account,
        "dest_bank": dest_bank,
        "dest_account": dest_account,
        "amount": amount,
        "description": (data.get("description") or "Transferencia desde el frontend").strip(),
    }, None, 200

# ── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def login():
    return render_template(
        'login.html',
        current_year=datetime.now().year,
        client_users=CLIENT_CREDENTIALS,
        selected_mode=request.args.get('mode', 'admin')
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/login', methods=['POST'])
def do_login():
    login_type = (request.form.get('login_type') or 'admin').strip().lower()
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''

    if login_type == 'admin':
        if username == 'admin' and password == 'admin':
            session.clear()
            session['user'] = 'admin'
            session['user_type'] = 'admin'
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Credenciales institucionales inválidas',
                               current_year=datetime.now().year, client_users=CLIENT_CREDENTIALS, selected_mode='admin')

    client = CLIENT_CREDENTIALS.get(username)
    if client and password == client.get('password'):
        session.clear()
        session['user'] = client.get('name', username)
        session['user_type'] = 'client'
        session['client_owner'] = username
        session['client_name'] = client.get('name', username)
        return redirect(url_for('transfers'))

    return render_template('login.html', error='Credenciales de cliente inválidas',
                           current_year=datetime.now().year, client_users=CLIENT_CREDENTIALS, selected_mode='client')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    client_redirect = _redirect_clients_to_transfers()
    if client_redirect:
        return client_redirect
    accounts = _get_visible_accounts()
    total_balance = sum(float(acc.get('numeric_balance', 0)) for acc in accounts)
    healthy_banks, avg_latency = check_bank_health()
    network_health = int((healthy_banks / len(BANKS)) * 100)
    balance_heights = get_balance_distribution(accounts)
    nodes, _ = get_cluster_state()
    leader_node = next((n for n in nodes if n.get('state') == 'LEADER'), None)
    transactions = _filter_transactions_for_session(get_all_transactions())
    today = datetime.now(timezone.utc).date()
    tx_today = 0
    for tx in transactions:
        try:
            if datetime.fromisoformat(tx.get('timestamp', '').replace('Z', '+00:00')).date() == today:
                tx_today += 1
        except Exception:
            pass
    summary = {
        'current_node': leader_node['name'] if leader_node else 'Líder no detectado',
        'current_role': 'Coordinador (líder)' if leader_node else 'Elección pendiente',
        'network_health': network_health,
        'latency': avg_latency,
        'last_sync': datetime.now().strftime('%H:%M:%S'),
        'consolidated_balance': total_balance,
        'balance_change': 'En vivo',
        'total_accounts': len(accounts),
        'total_regions': len(BANKS),
        'transactions_today': tx_today,
        'connected_banks': healthy_banks,
        'total_banks': len(BANKS),
        'cpu_load': 0,
        'balance_heights': balance_heights
    }
    user = get_user()
    return render_template('dashboard.html', summary=summary, user=user, active_page='dashboard')

@app.route('/accounts')
def accounts():
    if 'user' not in session:
        return redirect(url_for('login'))
    try:
        all_accounts = _get_visible_accounts()
    except Exception as e:
        print(f"Error obteniendo cuentas: {e}")
        all_accounts = []
    total_liquidity = sum(float(acc.get('numeric_balance', 0)) for acc in all_accounts)
    summary = {'total_accounts': len(all_accounts), 'total_liquidity': _format_money('MULTI', total_liquidity)}
    user = get_user()
    return render_template('accounts.html', user=user, active_page='accounts',
                           accounts=all_accounts, summary=summary)


@app.route('/clients')
def clients():
    if 'user' not in session:
        return redirect(url_for('login'))
    client_redirect = _redirect_clients_to_transfers()
    if client_redirect:
        return client_redirect
    try:
        all_accounts = _get_visible_accounts()
    except Exception as e:
        print(f"Error obteniendo clientes: {e}")
        all_accounts = []
    clients_data, stats, requirement_status = _build_clients_summary(all_accounts)
    banks = [{'id': bank, 'name': BANK_LABELS.get(bank, bank.capitalize())} for bank in BANKS]
    user = get_user()
    return render_template(
        'clients.html',
        user=user,
        active_page='clients',
        clients=clients_data,
        stats=stats,
        requirement_status=requirement_status,
        banks=banks,
        exchange_rates=EXCHANGE_RATES,
        is_admin=(not _is_client_session()),
    )

@app.route('/transfers')
def transfers():
    if 'user' not in session:
        return redirect(url_for('login'))
    banks = [{'id': bank, 'name': BANK_LABELS.get(bank, bank.capitalize())} for bank in BANKS]

    # Origen: el cliente solo puede usar sus cuentas. Admin puede usar todas para la demo.
    raw_source_accounts = _get_visible_accounts()
    source_accounts = [_decorate_account_for_transfer(acc) for acc in raw_source_accounts]

    # Destino: se muestran todas las cuentas existentes para permitir pagos a otros clientes.
    # La validación del backend mantiene restringida la cuenta origen del cliente autenticado.
    raw_destination_accounts = get_all_accounts_for_user()
    destination_accounts = [_decorate_account_for_transfer(acc) for acc in raw_destination_accounts]

    total_clients = len({acc['owner'] for acc in destination_accounts if acc.get('owner') and acc.get('owner') != '—'})
    user = get_user()
    return render_template('transfers.html', user=user, active_page='transfers',
                           banks=banks,
                           user_accounts=source_accounts,
                           destination_accounts=destination_accounts,
                           total_clients=total_clients,
                           is_client=_is_client_session(),
                           exchange_rates=EXCHANGE_RATES)

@app.route('/history')
def history():
    if 'user' not in session:
        return redirect(url_for('login'))
    transactions = []
    for tx in _filter_transactions_for_session(get_all_transactions()):
        timestamp = tx.get('timestamp', '')
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            date_text = dt.strftime('%Y-%m-%d')
            time_text = dt.strftime('%H:%M:%S')
        except Exception:
            date_text = '—'
            time_text = '—'
        transactions.append({
            'date': date_text,
            'time': time_text,
            'type': tx.get('type', 'Movimiento'),
            'source_bank': f"{tx.get('source_bank', '—')} · {tx.get('source_account', '—')}",
            'dest_bank': f"{tx.get('dest_bank', '—')} · {tx.get('dest_account', '—')}",
            'amount': _format_money(tx.get('currency', ''), float(tx.get('amount', 0))),
            'status': tx.get('status', 'desconocido')
        })
    banks = [{'name': name} for name in BANK_LABELS.values()]
    filters = {'date_range': 'Libro real'}
    user = get_user()
    return render_template('history.html', user=user, active_page='history',
                           transactions=transactions, banks=banks, filters=filters,
                           total_transactions=len(transactions))

@app.route('/banks')
def banks():
    if 'user' not in session:
        return redirect(url_for('login'))
    client_redirect = _redirect_clients_to_transfers()
    if client_redirect:
        return client_redirect
    accounts_by_bank = get_accounts_by_bank()
    nodes, _ = get_cluster_state()
    node_status_by_bank = {}
    priority_to_bank = {3: 'peru', 2: 'chile', 1: 'colombia'}
    for node in nodes:
        bank = priority_to_bank.get(node.get('priority'))
        if bank:
            node_status_by_bank[bank] = node.get('state')
    banks_data = {}
    for bank, accounts in accounts_by_bank.items():
        status = 'active' if node_status_by_bank.get(bank) not in ('DISCONNECTED', None) else 'inactive'
        volume = sum(float(acc.get('numeric_balance', 0)) for acc in accounts)
        banks_data[bank] = {
            'name': BANK_LABELS.get(bank, bank.capitalize()),
            'status': status,
            'accounts': len(accounts),
            'volume': _format_money('MULTI', volume),
            'last_sync': datetime.now().strftime('%H:%M:%S') if status == 'active' else 'no disponible',
            'sync_status': 'recent' if status == 'active' else 'stale'
        }
    leader_node = next((n for n in nodes if n.get('state') == 'LEADER'), None)
    coordinator = {
        'name': leader_node['name'] if leader_node else 'Sin coordinador',
        'status': 'Sincronizando nodos activos' if leader_node else 'Elección pendiente'
    }
    user = get_user()
    return render_template('banks.html', user=user, active_page='banks',
                           banks=banks_data, coordinator=coordinator)

def _prom_query(query):
    """Hace una query instantánea a Prometheus. Devuelve el primer valor numérico, o None."""
    try:
        r = http_requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                              params={"query": query}, timeout=2)
        data = r.json()
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
        return None
    except Exception:
        logger.debug("Consulta a Prometheus falló: %s", query, exc_info=True)
        return None

def _prom_query_all(query):
    """Devuelve todos los resultados de una query (para métricas por nodo)."""
    try:
        r = http_requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                              params={"query": query}, timeout=2)
        data = r.json()
        return data.get("data", {}).get("result", [])
    except Exception:
        logger.debug("Consulta múltiple a Prometheus falló: %s", query, exc_info=True)
        return []

@app.route('/monitoring')
def monitoring():
    if 'user' not in session:
        return redirect(url_for('login'))
    client_redirect = _redirect_clients_to_transfers()
    if client_redirect:
        return client_redirect

    prom_ok = _prom_query("up") is not None

    # ── KPIs principales ────────────────────────────────────────────────────
    # Total de transacciones por segundo (rate de 1 minuto sobre todos los nodos)
    tps_raw = _prom_query('sum(rate(bank_transactions_total[1m]))')
    throughput_tps = round((tps_raw or 0) * 60, 1)  # convertimos a TPM para mostrar

    # Latencia p99 del 2PC (fase prepare, que es la más lenta)
    latency_p99 = _prom_query(
        'histogram_quantile(0.99, sum by(le) (rate(bank_2pc_duration_seconds_bucket{phase="prepare"}[5m])))'
    )
    latency_ms = round((latency_p99 or 0) * 1000, 1)

    # Latencia p50 para calcular si subió o bajó
    latency_p50 = _prom_query(
        'histogram_quantile(0.50, sum by(le) (rate(bank_2pc_duration_seconds_bucket{phase="prepare"}[5m])))'
    )
    latency_p50_ms = round((latency_p50 or 0) * 1000, 1)
    latency_trend = "up" if latency_ms > latency_p50_ms else "down"
    latency_change = f"{'+' if latency_ms >= latency_p50_ms else ''}{round(latency_ms - latency_p50_ms, 1)}"

    # Estado de salud del cluster (nodos con state >= 0 = no pausados)
    node_states = _prom_query_all("bank_node_state")
    active_nodes = sum(1 for r in node_states if float(r["value"][1]) >= 0)
    total_nodes = len(node_states) if node_states else 3
    cluster_health = "Saludable" if active_nodes == total_nodes else (
        "Degradado" if active_nodes > 0 else "Crítico"
    )

    # ── Transacciones por minuto (últimos 10 intervalos de 1 min) ──────────
    tpm_raw = _prom_query_all(
        'sum by(node) (increase(bank_transactions_total[1m]))'
    )
    # Sacamos el total de cada nodo y normalizamos a alturas 0-100
    tpm_values = [round(float(r["value"][1])) for r in tpm_raw] if tpm_raw else [0, 0, 0]
    max_tpm = max(tpm_values) if tpm_values and max(tpm_values) > 0 else 1
    # Generamos 10 barras: los últimos valores reales + relleno si faltan
    tpm_heights = [round((v / max_tpm) * 100) for v in tpm_values]
    while len(tpm_heights) < 10:
        tpm_heights.insert(0, 0)
    tpm_heights = tpm_heights[-10:]  # últimas 10

    # ── Estado por nodo ────────────────────────────────────────────────────
    node_state_map = {1: "LÍDER", 0: "SEGUIDOR", -1: "PAUSADO"}
    node_colors = {"peru": "[#3b82f6]", "chile": "[#10b981]", "colombia": "[#f59e0b]"}
    nodes_metrics = []
    cpu_proxy = 0
    for r in node_states:
        node_name = r["metric"].get("node", r["metric"].get("exported_job", "?"))
        state_val = float(r["value"][1])
        # Usamos el contador de transacciones como proxy de "carga" del nodo (0-100)
        tx_rate = _prom_query(f'rate(bank_transactions_total{{node="{node_name}"}}[1m])') or 0
        cpu_proxy = min(100, round(tx_rate * 1000))  # escala visual
        nodes_metrics.append({
            "name": f"Nodo {node_name.capitalize()} ({node_state_map.get(int(state_val), '?')})",
            "cpu": cpu_proxy,
            "color": node_colors.get(node_name, "[#71717a]")
        })

    # Si Prometheus no responde, fallback a datos básicos reales del cluster
    if not prom_ok:
        healthy_banks, avg_latency = check_bank_health()
        nodes_metrics = [
            {"name": "Nodo Perú",     "cpu": 0, "color": "[#3b82f6]"},
            {"name": "Nodo Chile",    "cpu": 0, "color": "[#10b981]"},
            {"name": "Nodo Colombia", "cpu": 0, "color": "[#f59e0b]"},
        ]
        latency_ms = avg_latency
        cluster_health = "Saludable" if healthy_banks == 3 else "Degradado"
        throughput_tps = 0
        tpm_heights = [0] * 10

    # ── Logs del cluster desde los eventos gRPC ────────────────────────────
    logs = []
    for bank in BANKS:
        try:
            stub = get_stub(bank)
            resp = stub.GetEvents(bank_pb2.EventsRequest(), timeout=2)
            for evt in resp.events[-5:]:  # últimos 5 por nodo
                level = {"election": "INFO", "failure": "ALERTA", "sync": "OK", "transaction": "OK"}.get(evt.type, "INFO")
                logs.append({
                    "timestamp": evt.timestamp[:19].replace("T", " ") if evt.timestamp else "—",
                    "level": level,
                    "message": f"[{bank.upper()}] {evt.title}: {evt.description}"
                })
        except grpc.RpcError as exc:
            logger.warning("No se pudieron obtener eventos de %s: %s", bank, exc.code().name)
        except Exception:
            logger.exception("Error inesperado obteniendo eventos de %s", bank)
    logs.sort(key=lambda x: x["timestamp"], reverse=True)
    logs = logs[:20]

    metrics = {
        "cluster_health":    cluster_health,
        "time_range":        "1m",
        "cpu_load":          cpu_proxy if nodes_metrics else 0,
        "memory_used":       0,
        "memory_percent":    0,
        "latency_ms":        latency_ms,
        "latency_trend":     latency_trend,
        "latency_change":    latency_change,
        "throughput_tps":    throughput_tps,
        "throughput_status": cluster_health,
        "tpm_heights":       tpm_heights,
        "nodes":             nodes_metrics,
        "logs":              logs,
        "prometheus_ok":     prom_ok,
    }

    user = get_user()
    return render_template('monitoring.html', user=user, active_page='monitoring', metrics=metrics)

@app.route('/coordination')
def coordination():
    if 'user' not in session:
        return redirect(url_for('login'))
    client_redirect = _redirect_clients_to_transfers()
    if client_redirect:
        return client_redirect
    nodes, events = get_cluster_state()
    bank_name_map = {"peru": 3, "chile": 2, "colombia": 1}
    for node in nodes:
        for bank, node_id in bank_name_map.items():
            if node['priority'] == node_id:
                node['paused'] = manual_pause_state.get(bank, False)
                break
    leader_node = next((n for n in nodes if n['state'] == 'LEADER'), nodes[0])
    coordinator = {
        'name': leader_node['name'],
        'short_name': leader_node['short_name'],
        'details': f"ID: {leader_node['priority']}",
        'state': 'STABLE' if leader_node['state'] == 'LEADER' else 'ELECTION'
    }
    user = get_user()
    return render_template('coordination.html', user=user, active_page='coordination',
                           coordinator=coordinator, nodes=nodes, events=events)

@app.route('/error')
def error():
    if 'user' not in session:
        return redirect(url_for('login'))
    client_redirect = _redirect_clients_to_transfers()
    if client_redirect:
        return client_redirect
    recovery = {
        'status_message': 'RECUPERACIÓN AUTOMÁTICA EN PROCESO',
        'trigger': 'Umbral de espera alcanzado',
        'rollback_id': 'RBK-992-A',
        'routine': 'Sincronizando libro contable',
        'eta': '~15s',
        'button_text': 'Reintentar conexión'
    }
    failed_node = {'name': 'Nodo #3 (Colombia)', 'status': 'Desconectado', 'last_ping': 'hace 42s'}
    user = get_user() if 'user' in session else None
    return render_template('error.html', user=user, active_page='error',
                           recovery=recovery, failed_node=failed_node,
                           error_title='Restaurando estado del sistema',
                           error_message='El coordinador detectó una interrupción y está restaurando el estado del sistema.')

# ── API ──────────────────────────────────────────────────────────────────────

@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    global transactions_today_count
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'No autorizado'}), 401

    data = request.get_json(silent=True) or {}
    payload, error_msg, status_code = _validate_transfer_payload(data)
    if error_msg:
        _log_local_event('failure', 'Transferencia rechazada', error_msg)
        return jsonify({'success': False, 'message': error_msg}), status_code

    source_bank = payload['source_bank']
    source_account = payload['source_account']
    dest_bank = payload['dest_bank']
    dest_account = payload['dest_account']
    amount = payload['amount']
    description = payload['description']

    if not _account_belongs_to_session(source_account):
        return jsonify({'success': False, 'message': 'No puedes operar una cuenta origen que no pertenece al cliente autenticado'}), 403
    # El destino puede pertenecer a otro cliente; lo que se restringe es la cuenta origen.

    try:
        conversion = _conversion_details(amount, source_bank, source_account, dest_bank, dest_account)

        if source_bank == dest_bank:
            stub = get_stub(source_bank)
            resp = stub.TransferLocal(bank_pb2.TransferRequest(
                source_account=source_account,
                dest_account=dest_account,
                amount=amount,
                description=description
            ), timeout=5)
            if resp.success:
                transactions_today_count += 1
                _log_local_event(
                    'transaction',
                    'Transferencia local completada',
                    f"{source_account} -> {dest_account} "
                    f"({conversion['source_amount']} {conversion['source_currency']} / "
                    f"{conversion['destination_amount']} {conversion['destination_currency']})"
                )
                return jsonify({
                    'success': True,
                    'message': resp.message,
                    'tx_id': resp.transaction_id,
                    'conversion': conversion,
                })
            _log_local_event('failure', 'Transferencia local fallida', resp.message)
            return jsonify({'success': False, 'message': resp.message, 'conversion': conversion}), 400

        success, message, tx_id, conversion = execute_interbank_transfer(
            source_bank, source_account, dest_bank, dest_account, amount, description)
        if success:
            transactions_today_count += 1
            _log_local_event(
                'transaction',
                'Transferencia interbancaria completada',
                f"{source_account} -> {dest_account} "
                f"({conversion['source_amount']} {conversion['source_currency']} / "
                f"{conversion['destination_amount']} {conversion['destination_currency']})"
            )
            return jsonify({'success': True, 'message': message, 'tx_id': tx_id, 'conversion': conversion})
        _log_local_event('failure', 'Transferencia interbancaria fallida', message)
        return jsonify({'success': False, 'message': message, 'tx_id': tx_id, 'conversion': conversion}), 400
    except ValueError as e:
        message = str(e)
        logger.warning("Transferencia rechazada por datos inválidos: %s", message)
        _log_local_event('failure', 'Transferencia rechazada', message)
        return jsonify({'success': False, 'message': message}), 400
    except grpc.RpcError as e:
        message = f'Error del servicio bancario: {e.code().name}'
        logger.warning("Error RPC en transferencia %s -> %s: %s", source_account, dest_account, e.code().name)
        _log_local_event('failure', 'Error RPC en transferencia', message)
        return jsonify({'success': False, 'message': message}), 503
    except Exception as e:
        message = f'Error inesperado en transferencia: {e}'
        logger.exception("Error inesperado en transferencia %s -> %s", source_account, dest_account)
        _log_local_event('failure', 'Error en transferencia', message)
        return jsonify({'success': False, 'message': message}), 500


@app.route('/api/account-operation', methods=['POST'])
def api_account_operation():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'No autorizado'}), 401

    data = request.get_json(silent=True) or {}
    operation = (data.get('operation') or '').strip().lower()
    account_id = (data.get('account_id') or '').strip().upper()

    if operation not in ('deposit', 'withdraw'):
        return jsonify({'success': False, 'message': 'Operación inválida'}), 400
    if not account_id:
        return jsonify({'success': False, 'message': 'Selecciona una cuenta'}), 400

    try:
        amount = float(data.get('amount'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'El monto debe ser numérico'}), 400

    if amount <= 0:
        return jsonify({'success': False, 'message': 'El monto debe ser mayor que cero'}), 400

    bank = bank_from_account(account_id)
    if bank not in BANKS:
        return jsonify({'success': False, 'message': 'No se pudo identificar el banco de la cuenta'}), 400

    if not _account_belongs_to_session(account_id):
        return jsonify({'success': False, 'message': 'No puedes operar una cuenta que no pertenece al cliente autenticado'}), 403

    try:
        snapshot = _get_account_snapshot(bank, account_id)
        stub = get_stub(bank)
        request_pb = bank_pb2.TransactionRequest(account_id=account_id, amount=amount)
        if operation == 'deposit':
            resp = stub.Deposit(request_pb, timeout=5)
            operation_text = 'Depósito'
        else:
            resp = stub.Withdraw(request_pb, timeout=5)
            operation_text = 'Retiro'

        if not resp.success:
            _log_local_event('failure', f'{operation_text} rechazado', resp.message)
            return jsonify({'success': False, 'message': resp.message}), 400

        _log_local_event(
            'transaction',
            f'{operation_text} completado',
            f"{account_id} · {snapshot['currency']} {amount:,.2f}"
        )
        return jsonify({
            'success': True,
            'message': resp.message,
            'operation': operation,
            'account_id': account_id,
            'bank': bank,
            'bank_label': BANK_LABELS.get(bank, bank.capitalize()),
            'currency': snapshot['currency'],
            'amount': round(amount, 2),
            'new_balance': round(float(resp.new_balance), 2),
            'new_balance_text': _format_money(snapshot['currency'], float(resp.new_balance)),
        })
    except grpc.RpcError as e:
        message = f'Error del servicio bancario: {e.code().name}'
        logger.warning("Error RPC en operación %s sobre %s: %s", operation, account_id, e.code().name)
        _log_local_event('failure', 'Error RPC en operación de cuenta', message)
        return jsonify({'success': False, 'message': message}), 503
    except Exception as e:
        message = f'Error inesperado: {e}'
        logger.exception("Error inesperado en operación %s sobre %s", operation, account_id)
        _log_local_event('failure', 'Error en operación de cuenta', message)
        return jsonify({'success': False, 'message': message}), 500

@app.route('/coordination/data')
def coordination_data():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    forbidden = _client_forbidden_json()
    if forbidden:
        return forbidden
    nodes, _ = get_cluster_state()
    bank_name_map = {"peru": 3, "chile": 2, "colombia": 1}
    for node in nodes:
        for bank, node_id in bank_name_map.items():
            if node['priority'] == node_id:
                node['paused'] = manual_pause_state.get(bank, False)
                break
    leader_node = next((n for n in nodes if n['state'] == 'LEADER'), nodes[0])
    coordinator = {
        'name': leader_node['name'],
        'short_name': leader_node['short_name'],
        'details': f"ID: {leader_node['priority']}",
        'state': 'STABLE' if leader_node['state'] == 'LEADER' else 'ELECTION'
    }
    return jsonify({'nodes': nodes, 'coordinator': coordinator})

@app.route('/api/events')
def api_events():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    forbidden = _client_forbidden_json()
    if forbidden:
        return forbidden
    all_events = list(local_event_log)
    for bank in BANKS:
        try:
            stub = get_stub(bank)
            resp = stub.GetEvents(bank_pb2.EventsRequest(), timeout=2)
            for evt in resp.events:
                all_events.append({
                    "timestamp": evt.timestamp,
                    "type": evt.type,
                    "title": evt.title,
                    "description": evt.description
                })
        except grpc.RpcError as exc:
            logger.warning("No se pudieron obtener eventos de %s: %s", bank, exc.code().name)
        except Exception:
            logger.exception("Error inesperado obteniendo eventos de %s", bank)
    seen = set()
    unique_events = []
    for e in sorted(all_events, key=lambda x: x.get('timestamp', ''), reverse=True):
        key = (e.get('timestamp', ''), e.get('title', ''))
        if key not in seen:
            seen.add(key)
            unique_events.append(e)
    return jsonify(unique_events[:30])

NODE_ID_MAPPING = {"3": "peru", "2": "chile", "1": "colombia"}
BANK_NODE_IDS   = {"peru": "3", "chile": "2", "colombia": "1"}

def _bank_from_node_label(label):
    if not label:
        return None
    if label.startswith("Node #") or label.startswith("Nodo #"):
        num = label.split("#")[1].split(" ")[0].strip()
        return NODE_ID_MAPPING.get(num)
    if label.startswith("N") and len(label) >= 2 and label[1].isdigit():
        return NODE_ID_MAPPING.get(label[1])
    return None

def _trigger_election_on_active_nodes(exclude_bank=None):
    """Tell all non-paused peers to run a bully election (candidate_id=0 → lowest possible, any node wins)."""
    for bank in BANKS:
        if bank == exclude_bank:
            continue
        if manual_pause_state.get(bank, False):
            continue
        try:
            stub = get_stub(bank)
            stub.Election(bank_pb2.ElectionRequest(candidate_id="0"), timeout=2)
        except Exception:
            logger.warning("No se pudo activar elección en %s", bank, exc_info=True)

@app.route('/api/force-election', methods=['POST'])
def force_election():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'No autorizado'}), 401
    forbidden = _client_forbidden_json()
    if forbidden:
        return forbidden
    data = request.get_json(silent=True) or {}
    target_node = data.get('node')
    if target_node:
        bank = _bank_from_node_label(target_node)
        if not bank or bank not in BANKS:
            return jsonify({"error": f"Nodo no encontrado: {target_node}"}), 404
        _trigger_election_on_active_nodes()
        _log_local_event("election",
                         f"Elección forzada en {target_node}",
                         f"Se envió la elección manual a todos los nodos activos")
    else:
        _trigger_election_on_active_nodes()
        _log_local_event("election",
                         "Elección global activada",
                         "Se envió la señal de elección manual a todos los nodos activos del clúster")
    return jsonify({"success": True})

@app.route('/api/node/<path:node_id>/toggle', methods=['POST'])
def toggle_node(node_id):
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'No autorizado'}), 401
    forbidden = _client_forbidden_json()
    if forbidden:
        return forbidden
    from urllib.parse import unquote
    node_id = unquote(node_id)
    bank = _bank_from_node_label(node_id)
    if not bank:
        return jsonify({"error": f"Nodo no encontrado: {node_id}"}), 404

    # Determine current node state before toggling
    nodes, _ = get_cluster_state()
    bank_priority = {"peru": 3, "chile": 2, "colombia": 1}
    target_priority = bank_priority[bank]
    current_node = next((n for n in nodes if n['priority'] == target_priority), None)
    was_leader = current_node and current_node['state'] == 'LEADER'

    new_pause = not manual_pause_state[bank]
    manual_pause_state[bank] = new_pause
    action = "pausado" if new_pause else "reanudado"

    # ── 1. Tell the gRPC server to pause/resume ──────────────────────────────
    grpc_error = None
    try:
        stub = get_stub(bank)
        stub.SetNodeStatus(bank_pb2.NodeStatusRequest(paused=new_pause), timeout=2)
    except Exception as e:
        grpc_error = str(e)
        logger.warning("No se pudo aplicar %s en el nodo gRPC %s: %s", action, bank, e)

    # ── 2. Bully logic on pause ──────────────────────────────────────────────
    if new_pause and was_leader:
        # The leader just went down → trigger election on remaining active nodes
        # Give the server a moment to apply the pause before we send Elección messages
        time.sleep(0.3)
        _trigger_election_on_active_nodes(exclude_bank=bank)
        _log_local_event("election",
                         f"Elección activada — {node_id} (líder) pausado",
                         "Algoritmo Bully: los nodos restantes están eligiendo un nuevo coordinador")
    elif new_pause and not was_leader:
        _log_local_event("failure",
                         f"{node_id} pausado",
                         "Nodo pausado manualmente. Los latidos del líder ya no llegarán a este nodo.")
    # ── 3. Bully logic on resume ─────────────────────────────────────────────
    # ── 3. Bully logic on resume ─────────────────────────────────────────────
    elif not new_pause:
        time.sleep(0.3)
        node_id_int = target_priority  # prioridad real del nodo que vuelve (3=perú, 2=chile, 1=colombia)
        
        # El nodo que regresa se anuncia con su ID real.
        # Los nodos de menor prioridad recibirán candidate_id > su propio id
        # → se rinden y pasan a FOLLOWER esperando el mensaje Coordinador.
        try:
            stub = get_stub(bank)
            stub.Election(bank_pb2.ElectionRequest(candidate_id=str(node_id_int)), timeout=2)
        except Exception:
            logger.warning("No se pudo anunciar el regreso del nodo %s", bank, exc_info=True)

        # También notificamos a los demás nodos activos con el ID real del que vuelve,
        # para que los de menor prioridad se rindan correctamente.
        for other_bank in BANKS:
            if other_bank == bank:
                continue
            if manual_pause_state.get(other_bank, False):
                continue
            try:
                stub2 = get_stub(other_bank)
                stub2.Election(bank_pb2.ElectionRequest(candidate_id=str(node_id_int)), timeout=2)
            except Exception:
                logger.warning("No se pudo notificar el regreso del nodo a %s", other_bank, exc_info=True)

        _log_local_event("sync",
                        f"{node_id} reanudado — volviendo al clúster",
                        f"Bully: el nodo {node_id_int} se anuncia; los nodos de menor prioridad ceden")

    msg = f"Nodo {node_id} {action}"
    if grpc_error:
        msg += " (estado local actualizado — gRPC no disponible)"
    return jsonify({"success": True, "paused": new_pause, "message": msg,
                    **({"warning": grpc_error} if grpc_error else {})})

@app.route('/api/export-logs')
def export_logs():
    if 'user' not in session:
        return redirect(url_for('login'))
    forbidden = _client_forbidden_json()
    if forbidden:
        return forbidden
    lines = []
    for evt in local_event_log:
        lines.append(f"[LOCAL][{evt['timestamp']}] {evt['title']}: {evt['description']}")
    for bank in BANKS:
        try:
            stub = get_stub(bank)
            resp = stub.GetEvents(bank_pb2.EventsRequest(), timeout=2)
            lines.append(f"--- {bank} ---")
            for evt in resp.events:
                lines.append(f"[{evt.timestamp}] {evt.title}: {evt.description}")
        except Exception:
            logger.warning("No se pudieron exportar logs de %s", bank, exc_info=True)
            lines.append(f"--- {bank} (no disponible) ---")
    content = "\n".join(lines)
    return Response(content, mimetype="text/plain",
                    headers={"Content-Disposition": "attachment;filename=coordination-logs.txt"})

if __name__ == '__main__':
    app.run(
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', '5000')),
        debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    )
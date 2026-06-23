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

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'clave-por-defecto')

transactions_today_count = 0
manual_pause_state = {bank: False for bank in BANKS}
local_event_log = []

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")


def _log_local_event(etype, title, description):
    local_event_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": etype,
        "title": title,
        "description": description
    })
    if len(local_event_log) > 100:
        local_event_log.pop(0)

def get_user():
    return {
        'name': session.get('user', 'Admin'),
        'bank_name': 'Global Finance',
        'role': 'Nodo institucional #12',
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
        except Exception:
            pass
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

def _account_exists_in_bank(bank, account_id):
    try:
        stub = get_stub(bank)
        stub.GetBalance(bank_pb2.BalanceRequest(account_id=account_id), timeout=2)
        return True
    except Exception:
        return False

def _validate_transfer_payload(data):
    required = ["source_bank", "source_account", "dest_bank", "dest_account", "amount"]
    missing = [field for field in required if field not in data or data.get(field) is None or data.get(field) == ""]
    if missing:
        return None, f"Faltan campos: {', '.join(missing)}"

    source_bank = data["source_bank"]
    dest_bank = data["dest_bank"]
    source_account = data["source_account"].strip().upper()
    dest_account = data["dest_account"].strip().upper()

    if source_bank not in BANKS or dest_bank not in BANKS:
        return None, "Banco seleccionado inválido"

    try:
        amount = float(data["amount"])
    except (TypeError, ValueError):
        return None, "El monto debe ser numérico"

    if amount <= 0:
        return None, "El monto debe ser mayor que cero"

    if source_account == dest_account:
        return None, "La cuenta origen y destino deben ser distintas"

    if bank_from_account(source_account) != source_bank:
        return None, "La cuenta origen no pertenece al banco seleccionado"

    if bank_from_account(dest_account) != dest_bank:
        return None, "La cuenta destino no pertenece al banco seleccionado"

    if not _account_exists_in_bank(source_bank, source_account):
        return None, "Cuenta origen no encontrada"

    if not _account_exists_in_bank(dest_bank, dest_account):
        return None, "Cuenta destino no encontrada"

    return {
        "source_bank": source_bank,
        "source_account": source_account,
        "dest_bank": dest_bank,
        "dest_account": dest_account,
        "amount": amount,
        "description": (data.get("description") or "Transferencia desde el frontend").strip(),
    }, None

# ── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def login():
    return render_template('login.html', current_year=datetime.now().year)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/login', methods=['POST'])
def do_login():
    username = request.form['username']
    password = request.form['password']
    if username == 'admin' and password == 'admin':
        session['user'] = username
        return redirect(url_for('dashboard'))
    return render_template('login.html', error='Credenciales inválidas', current_year=datetime.now().year)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    accounts = get_all_accounts_for_user(session['user'])
    total_balance = sum(float(acc.get('numeric_balance', 0)) for acc in accounts)
    healthy_banks, avg_latency = check_bank_health()
    network_health = int((healthy_banks / len(BANKS)) * 100)
    balance_heights = get_balance_distribution(accounts)
    nodes, _ = get_cluster_state()
    leader_node = next((n for n in nodes if n.get('state') == 'LEADER'), None)
    transactions = get_all_transactions()
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
        all_accounts = get_all_accounts_for_user(session['user'])
    except Exception as e:
        print(f"Error obteniendo cuentas: {e}")
        all_accounts = []
    total_liquidity = sum(float(acc.get('numeric_balance', 0)) for acc in all_accounts)
    summary = {'total_accounts': len(all_accounts), 'total_liquidity': _format_money('MULTI', total_liquidity)}
    user = get_user()
    return render_template('accounts.html', user=user, active_page='accounts',
                           accounts=all_accounts, summary=summary)

@app.route('/transfers')
def transfers():
    if 'user' not in session:
        return redirect(url_for('login'))
    banks = [{'id': bank, 'name': BANK_LABELS.get(bank, bank.capitalize())} for bank in BANKS]
    user_accounts = [
        {'number': acc['number'], 'bank': acc['bank'], 'bank_id': acc['bank_id'], 'currency': acc['currency'], 'balance': acc['balance']}
        for acc in get_all_accounts_for_user(session['user'])
    ]
    user = get_user()
    return render_template('transfers.html', user=user, active_page='transfers',
                           banks=banks, user_accounts=user_accounts)

@app.route('/history')
def history():
    if 'user' not in session:
        return redirect(url_for('login'))
    transactions = []
    for tx in get_all_transactions():
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
    filters = {'date_range': 'Real ledger'}
    user = get_user()
    return render_template('history.html', user=user, active_page='history',
                           transactions=transactions, banks=banks, filters=filters,
                           total_transactions=len(transactions))

@app.route('/banks')
def banks():
    if 'user' not in session:
        return redirect(url_for('login'))
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
        return None

def _prom_query_all(query):
    """Devuelve todos los resultados de una query (para métricas por nodo)."""
    try:
        r = http_requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                              params={"query": query}, timeout=2)
        data = r.json()
        return data.get("data", {}).get("result", [])
    except Exception:
        return []

@app.route('/monitoring')
def monitoring():
    if 'user' not in session:
        return redirect(url_for('login'))

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
                level = {"election": "INFO", "failure": "WARN", "sync": "SUCCESS"}.get(evt.type, "INFO")
                logs.append({
                    "timestamp": evt.timestamp[:19].replace("T", " ") if evt.timestamp else "—",
                    "level": level,
                    "message": f"[{bank.upper()}] {evt.title}: {evt.description}"
                })
        except Exception:
            pass
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
                           error_message='The coordinator detected a disruption...')

# ── API ──────────────────────────────────────────────────────────────────────

@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    global transactions_today_count
    data = request.get_json(silent=True) or {}
    payload, error_msg = _validate_transfer_payload(data)
    if error_msg:
        _log_local_event('failure', 'Transferencia rechazada', error_msg)
        return jsonify({'success': False, 'message': error_msg}), 400

    source_bank = payload['source_bank']
    source_account = payload['source_account']
    dest_bank = payload['dest_bank']
    dest_account = payload['dest_account']
    amount = payload['amount']
    description = payload['description']

    try:
        if source_bank == dest_bank:
            stub = get_stub(source_bank)
            resp = stub.TransferLocal(bank_pb2.TransferRequest(
                source_account=source_account, dest_account=dest_account,
                amount=amount, description=description), timeout=5)
            if resp.success:
                transactions_today_count += 1
                _log_local_event('transaction', 'Transferencia local completada', f'{source_account} -> {dest_account} ({amount})')
                return jsonify({'success': True, 'message': resp.message, 'tx_id': resp.transaction_id})
            _log_local_event('failure', 'Transferencia local fallida', resp.message)
            return jsonify({'success': False, 'message': resp.message}), 400

        success, message, tx_id = execute_interbank_transfer(
            source_bank, source_account, dest_bank, dest_account, amount, description)
        if success:
            transactions_today_count += 1
            _log_local_event('transaction', 'Transferencia interbancaria completada', f'{source_account} -> {dest_account} ({amount})')
            return jsonify({'success': True, 'message': message, 'tx_id': tx_id})
        _log_local_event('failure', 'Transferencia interbancaria fallida', message)
        return jsonify({'success': False, 'message': message, 'tx_id': tx_id}), 400
    except grpc.RpcError as e:
        message = f'Error del servicio bancario: {e.code().name}'
        _log_local_event('failure', 'Error RPC en transferencia', message)
        return jsonify({'success': False, 'message': message}), 503
    except Exception as e:
        message = f'Error inesperado en transferencia: {e}'
        _log_local_event('failure', 'Error en transferencia', message)
        return jsonify({'success': False, 'message': message}), 500

@app.route('/coordination/data')
def coordination_data():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
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
        except Exception:
            pass
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
            pass

@app.route('/api/force-election', methods=['POST'])
def force_election():
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
            pass

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
                pass

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
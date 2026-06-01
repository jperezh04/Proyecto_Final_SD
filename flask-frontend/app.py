import os
import time
import grpc
from datetime import datetime, timezone

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from dotenv import load_dotenv

from bank_client import get_all_accounts_for_user, get_stub, BANKS
import bank_pb2
import bank_pb2_grpc
from two_phase_commit import execute_interbank_transfer
from bully import get_cluster_state

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'clave-por-defecto')

# Contador global de transacciones
transactions_today_count = 0

# Estado de pausa manual (controlado desde la UI, refleja lo que enviamos al gRPC)
manual_pause_state = {bank: False for bank in BANKS}

# Log de eventos local para cuando los nodos no están disponibles
local_event_log = []

def _log_local_event(etype, title, description):
    local_event_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": etype,
        "title": title,
        "description": description
    })
    # Keep last 100 events
    if len(local_event_log) > 100:
        local_event_log.pop(0)

# ------------------------------------------------------------
# Funciones auxiliares
# ------------------------------------------------------------
def get_user():
    return {
        'name': session.get('user', 'Admin'),
        'bank_name': 'Global Finance',
        'role': 'Institutional Node #12',
        'avatar_url': 'https://ui-avatars.com/api/?name=Admin&background=316bf3&color=fff'
    }

def check_bank_health():
    test_accounts = {"peru": "PE001", "chile": "CH001", "colombia": "CO001"}
    healthy = 0
    total_latency = 0
    for bank, address in BANKS.items():
        try:
            start = time.time()
            stub = get_stub(bank)
            stub.GetBalance(bank_pb2.BalanceRequest(account_id=test_accounts[bank]), timeout=2)
            latency = (time.time() - start) * 1000
            healthy += 1
            total_latency += latency
        except grpc.RpcError as e:
            if e.code() in (grpc.StatusCode.NOT_FOUND, grpc.StatusCode.OK):
                healthy += 1
                latency = (time.time() - start) * 1000
                total_latency += latency
        except Exception:
            pass
    avg_latency = round(total_latency / healthy) if healthy > 0 else 0
    return healthy, avg_latency

def get_balance_distribution(accounts):
    distribution = {"peru": 0, "chile": 0, "colombia": 0}
    for acc in accounts:
        if acc['number'].startswith('PE'):
            distribution['peru'] += float(acc['balance'].replace('$','').replace(',',''))
        elif acc['number'].startswith('CH'):
            distribution['chile'] += float(acc['balance'].replace('$','').replace(',',''))
        elif acc['number'].startswith('CO'):
            distribution['colombia'] += float(acc['balance'].replace('$','').replace(',',''))
    max_balance = max(distribution.values()) if distribution else 1
    heights = [int((v / max_balance) * 100) if max_balance > 0 else 0 for v in distribution.values()]
    return heights

# ------------------------------------------------------------
# Rutas de la aplicación
# ------------------------------------------------------------
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
    else:
        return render_template('login.html', error='Invalid credentials', current_year=datetime.now().year)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    accounts = get_all_accounts_for_user(session['user'])
    total_balance = sum(float(acc['balance'].replace('$','').replace(',','')) for acc in accounts)
    healthy_banks, avg_latency = check_bank_health()
    network_health = int((healthy_banks / len(BANKS)) * 100)
    balance_heights = get_balance_distribution(accounts)
    summary = {
        'current_node': 'Node #1 Peru',
        'current_role': 'Coordinator (Leader)',
        'network_health': network_health,
        'latency': avg_latency,
        'last_sync': 'Just now',
        'consolidated_balance': total_balance,
        'balance_change': '+2.4%',
        'total_accounts': len(accounts),
        'total_regions': 3,
        'transactions_today': transactions_today_count,
        'connected_banks': healthy_banks,
        'total_banks': len(BANKS),
        'cpu_load': 32,
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
    summary = {'total_accounts': len(all_accounts), 'total_liquidity': '$482.5M'}
    user = get_user()
    return render_template('accounts.html', user=user, active_page='accounts',
                           accounts=all_accounts, summary=summary)

@app.route('/transfers')
def transfers():
    if 'user' not in session:
        return redirect(url_for('login'))
    banks = [
        {'id': 'peru', 'name': 'Global Finance (Peru)'},
        {'id': 'chile', 'name': 'Banco Chile'},
        {'id': 'colombia', 'name': 'Banco Colombia'}
    ]
    user_accounts = [
        {'number': 'PE001', 'bank': 'Global Finance (Peru)'},
        {'number': 'PE002', 'bank': 'Global Finance (Peru)'},
        {'number': 'CH001', 'bank': 'Banco Chile'},
        {'number': 'CO001', 'bank': 'Banco Colombia'}
    ]
    user = get_user()
    return render_template('transfers.html', user=user, active_page='transfers',
                           banks=banks, user_accounts=user_accounts)

@app.route('/history')
def history():
    if 'user' not in session:
        return redirect(url_for('login'))
    transactions = [
        {'date': '2023-10-31', 'time': '14:32:05', 'type': 'Wire Transfer',
         'source_bank': 'JPMorgan Chase', 'dest_bank': 'Node #12 (Internal)',
         'amount': '+$12,500,000.00', 'status': 'successful'},
    ]
    banks = [{'name': 'JPMorgan Chase'}, {'name': 'Goldman Sachs'}, {'name': 'Morgan Stanley'}]
    filters = {'date_range': 'Oct 1 - Oct 31, 2023'}
    user = get_user()
    return render_template('history.html', user=user, active_page='history',
                           transactions=transactions, banks=banks, filters=filters,
                           total_transactions=142)

@app.route('/banks')
def banks():
    if 'user' not in session:
        return redirect(url_for('login'))
    banks_data = {
        'peru': {'name': 'Peru Node', 'status': 'active', 'accounts': 14205,
                 'volume': '$2.4M', 'last_sync': '2s ago', 'sync_status': 'recent'},
        'chile': {'name': 'Chile Node', 'status': 'active', 'accounts': 8450,
                  'volume': '$1.1M', 'last_sync': '5s ago', 'sync_status': 'recent'},
        'colombia': {'name': 'Colombia Node', 'status': 'active', 'accounts': 28910,
                     'volume': '$5.1M', 'last_sync': 'Just now', 'sync_status': 'recent'}
    }
    coordinator = {'name': 'HQ Master', 'status': 'Syncing active nodes'}
    user = get_user()
    return render_template('banks.html', user=user, active_page='banks',
                           banks=banks_data, coordinator=coordinator)

@app.route('/monitoring')
def monitoring():
    if 'user' not in session:
        return redirect(url_for('login'))
    metrics = {
        'cluster_health': 'Healthy',
        'time_range': '15m',
        'cpu_load': 42,
        'memory_used': 28.4,
        'memory_percent': 65,
        'latency_ms': 124,
        'latency_trend': 'up',
        'latency_change': '+12',
        'throughput_tps': 8492,
        'throughput_status': 'Healthy',
        'tpm_heights': [60, 75, 40, 90, 85, 65, 50, 80, 95, 70],
        'nodes': [
            {'name': 'Node-A', 'cpu': 75, 'color': '[#3b82f6]'},
            {'name': 'Node-B', 'cpu': 45, 'color': '[#10b981]'},
            {'name': 'Node-C', 'cpu': 82, 'color': '[#f59e0b]'},
        ],
        'logs': [
            {'timestamp': '2023-10-27 14:32:01.442', 'level': 'INFO', 'message': 'Node-C initiated Bully Election.'},
            {'timestamp': '2023-10-27 14:32:01.450', 'level': 'SUCCESS', 'message': 'Node-D broadcasts Victory.'},
        ]
    }
    user = get_user()
    return render_template('monitoring.html', user=user, active_page='monitoring', metrics=metrics)

@app.route('/coordination')
def coordination():
    if 'user' not in session:
        return redirect(url_for('login'))
    nodes, events = get_cluster_state()
    # Annotate pause state from local mirror
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
        'status_message': 'AUTOMATIC RECOVERY IN PROGRESS',
        'trigger': 'Timeout Threshold Reached',
        'rollback_id': 'RBK-992-A',
        'routine': 'Synchronizing Ledger',
        'eta': '~15s',
        'button_text': 'Retry Connection'
    }
    failed_node = {'name': 'Node #3 (Colombia)', 'status': 'Disconnected', 'last_ping': '42s ago'}
    user = get_user() if 'user' in session else None
    return render_template('error.html', user=user, active_page='error',
                           recovery=recovery, failed_node=failed_node,
                           error_title='System state restoring',
                           error_message='The coordinator detected a disruption...')

# ------------------------------------------------------------
# Endpoints API
# ------------------------------------------------------------
@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    global transactions_today_count
    data = request.get_json()
    source_bank = data['source_bank']
    source_account = data['source_account']
    dest_bank = data['dest_bank']
    dest_account = data['dest_account']
    amount = float(data['amount'])

    if source_bank == dest_bank:
        stub = get_stub(source_bank)
        resp = stub.TransferLocal(bank_pb2.TransferRequest(
            source_account=source_account,
            dest_account=dest_account,
            amount=amount,
            description="Local transfer from frontend"
        ))
        if resp.success:
            transactions_today_count += 1
            return jsonify({'success': True, 'message': resp.message, 'tx_id': resp.transaction_id})
        else:
            return jsonify({'success': False, 'message': resp.message})
    else:
        success, message, tx_id = execute_interbank_transfer(
            source_bank, source_account, dest_bank, dest_account, amount
        )
        if success:
            transactions_today_count += 1
        return jsonify({'success': success, 'message': message, 'tx_id': tx_id})

@app.route('/coordination/data')
def coordination_data():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
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
    return jsonify({'nodes': nodes, 'coordinator': coordinator})

@app.route('/api/events')
def api_events():
    """Recolecta eventos de todos los nodos gRPC + log local, los mezcla y devuelve los más recientes."""
    all_events = list(local_event_log)  # start with local events

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
            pass  # node unreachable — local events cover frontend actions

    # Sort newest first, deduplicate by (timestamp, title)
    seen = set()
    unique_events = []
    for e in sorted(all_events, key=lambda x: x.get('timestamp', ''), reverse=True):
        key = (e.get('timestamp', ''), e.get('title', ''))
        if key not in seen:
            seen.add(key)
            unique_events.append(e)

    return jsonify(unique_events[:30])

NODE_ID_MAPPING = {"3": "peru", "2": "chile", "1": "colombia"}
BANK_NODE_IDS  = {"peru": "3", "chile": "2", "colombia": "1"}

def _bank_from_node_label(label):
    """Extract bank name from labels like 'Node #3 (Peru)' or 'N3'."""
    if not label:
        return None
    if label.startswith("Node #"):
        num = label.split("#")[1].split(" ")[0].strip()
        return NODE_ID_MAPPING.get(num)
    if label.startswith("N") and len(label) >= 2 and label[1].isdigit():
        return NODE_ID_MAPPING.get(label[1])
    return None

@app.route('/api/force-election', methods=['POST'])
def force_election():
    data = request.get_json(silent=True) or {}
    target_node = data.get('node')
    ts = datetime.now(timezone.utc).isoformat()

    if target_node:
        bank = _bank_from_node_label(target_node)
        if bank and bank in BANKS:
            # Send election to all nodes (bully: lower-priority triggers election)
            for b in BANKS:
                try:
                    stub = get_stub(b)
                    stub.Election(bank_pb2.ElectionRequest(candidate_id="0"), timeout=2)
                except Exception:
                    pass
            _log_local_event("election",
                             f"Election forced on {target_node}",
                             f"Manual election trigger sent to all nodes from {target_node}")
            return jsonify({"success": True})
        return jsonify({"error": f"Node not found: {target_node}"}), 404
    else:
        for bank in BANKS:
            try:
                stub = get_stub(bank)
                stub.Election(bank_pb2.ElectionRequest(candidate_id="0"), timeout=2)
            except Exception:
                pass
        _log_local_event("election",
                         "Global election triggered",
                         "Manual election signal sent to all nodes in the cluster")
        return jsonify({"success": True})

@app.route('/api/node/<path:node_id>/toggle', methods=['POST'])
def toggle_node(node_id):
    from urllib.parse import unquote
    node_id = unquote(node_id)
    bank = _bank_from_node_label(node_id)
    if not bank:
        return jsonify({"error": f"Node not found: {node_id}"}), 404

    new_state = not manual_pause_state[bank]
    manual_pause_state[bank] = new_state
    action = "paused" if new_state else "resumed"

    # Try to notify the gRPC server
    grpc_ok = False
    grpc_error = None
    try:
        stub = get_stub(bank)
        resp = stub.SetNodeStatus(bank_pb2.NodeStatusRequest(paused=new_state), timeout=2)
        grpc_ok = resp.success
    except Exception as e:
        grpc_error = str(e)

    # Always log the action locally so the timeline reflects it
    evt_type = "failure" if new_state else "sync"
    _log_local_event(evt_type,
                     f"{node_id} {action}",
                     f"Node manually {action} via dashboard" + (" (server unreachable)" if grpc_error else ""))

    if grpc_ok:
        return jsonify({"success": True, "paused": new_state, "message": f"Node {node_id} {action}"})
    else:
        return jsonify({
            "success": True,
            "paused": new_state,
            "message": f"Node {node_id} {action} (local state updated)",
            "warning": grpc_error or "gRPC server did not confirm"
        })

@app.route('/api/export-logs')
def export_logs():
    lines = []
    # Include local events
    for evt in local_event_log:
        lines.append(f"[LOCAL][{evt['timestamp']}] {evt['title']}: {evt['description']}")
    # Include gRPC events
    for bank in BANKS:
        try:
            stub = get_stub(bank)
            resp = stub.GetEvents(bank_pb2.EventsRequest(), timeout=2)
            lines.append(f"--- {bank} ---")
            for evt in resp.events:
                lines.append(f"[{evt.timestamp}] {evt.title}: {evt.description}")
        except Exception:
            lines.append(f"--- {bank} (unreachable) ---")
    content = "\n".join(lines)
    return Response(content, mimetype="text/plain",
                    headers={"Content-Disposition": "attachment;filename=coordination-logs.txt"})

# ------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True)

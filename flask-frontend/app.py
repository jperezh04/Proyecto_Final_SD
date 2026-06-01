
import os

from bank_client import get_all_accounts_for_user
from flask import Flask, render_template, session, redirect, url_for, request

from dotenv import load_dotenv
from datetime import datetime 


load_dotenv()  # Carga el archivo .env

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'clave-por-defecto')

# Datos dummy (luego vendrán de gRPC)
def get_dummy_summary():
    return {
        'total_accounts': 5,
        'total_balance': 47650.75,
        'current_bank': 'Banco Perú',
        'coordinator_node': 'Banco Perú (ID 3)',
        'is_leader': True
    }

def get_dummy_accounts():
    return [
        {'account_number': 'PE001', 'bank': 'peru', 'country': 'Perú',
         'type': 'Ahorros', 'balance': 15000.00, 'status': 'activa'},
        {'account_number': 'CH002', 'bank': 'chile', 'country': 'Chile',
         'type': 'Corriente', 'balance': 3200.50, 'status': 'activa'},
        # ... más cuentas
    ]

# Rutas de páginas
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
    # Validación de ejemplo (luego conectas con backend gRPC)
    if username == 'admin' and password == 'admin':
        session['user'] = username
        return redirect(url_for('dashboard'))
    else:
        return render_template('login.html', error='Invalid credentials', current_year=datetime.now().year)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    # Obtener cuentas para calcular totales
    accounts = get_all_accounts_for_user(session['user'])
    total_balance = sum(float(acc['balance'].replace('$','').replace(',','')) for acc in accounts)
    
    summary = {
        'current_node': 'Node #1 Peru',
        'current_role': 'Coordinator (Leader)',
        'network_health': 100,
        'latency': 12,
        'last_sync': 'Just now',
        'consolidated_balance': total_balance,
        'balance_change': '+2.4%',
        'total_accounts': len(accounts),
        'total_regions': 3,
        'transactions_today': 0,  # Luego lo calcularemos
        'connected_banks': 3,
        'total_banks': 3,
        'cpu_load': 32
    }
    user = get_user()
    return render_template('dashboard.html',
                           summary=summary,
                           user=user,
                           active_page='dashboard')
    
@app.route('/accounts')
def accounts():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    # Obtener cuentas reales de todos los bancos
    try:
        all_accounts = get_all_accounts_for_user(session['user'])
    except Exception as e:
        print(f"Error obteniendo cuentas: {e}")
        all_accounts = []
    
    summary = {
        'total_accounts': len(all_accounts),
        'total_liquidity': '$482.5M'  # Por ahora fijo
    }
    user = get_user()
    return render_template('accounts.html',
                           user=user,
                           active_page='accounts',
                           accounts=all_accounts,
                           summary=summary)
    
@app.route('/transfers')
def transfers():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Datos dummy de bancos y cuentas del usuario
    banks = [
        {'id': 'peru', 'name': 'Global Finance (Perú)'},
        {'id': 'chile', 'name': 'Banco Chile'},
        {'id': 'colombia', 'name': 'Banco Colombia'}
    ]
    user_accounts = [
        {'number': 'PE001', 'bank': 'Global Finance (Perú)'},
        {'number': 'PE002', 'bank': 'Global Finance (Perú)'},
        {'number': 'CH001', 'bank': 'Banco Chile'},
        {'number': 'CO001', 'bank': 'Banco Colombia'}
    ]

    user = get_user()
    return render_template('transfers.html',
                           user=user,
                           active_page='transfers',
                           banks=banks,
                           user_accounts=user_accounts)
@app.route('/history')
def history():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Datos dummy de transacciones (luego vendrán de gRPC)
    transactions = [
        {
            'date': '2023-10-31',
            'time': '14:32:05',
            'type': 'Wire Transfer',
            'source_bank': 'JPMorgan Chase',
            'dest_bank': 'Node #12 (Internal)',
            'amount': '+$12,500,000.00',
            'status': 'successful'
        },
        {
            'date': '2023-10-31',
            'time': '11:15:22',
            'type': 'FX Settlement',
            'source_bank': 'Node #12 (Internal)',
            'dest_bank': 'Barclays PLC',
            'amount': '-$4,250,000.00',
            'status': 'pending'
        },
        {
            'date': '2023-10-30',
            'time': '09:45:00',
            'type': 'ACH Settlement',
            'source_bank': 'Citigroup',
            'dest_bank': 'Node #12 (Internal)',
            'amount': '+$850,000.00',
            'status': 'successful'
        },
        {
            'date': '2023-10-30',
            'time': '08:12:33',
            'type': 'Wire Transfer',
            'source_bank': 'Node #12 (Internal)',
            'dest_bank': 'Unknown Institution',
            'amount': '-$15,000,000.00',
            'status': 'error'
        },
        {
            'date': '2023-10-29',
            'time': '16:55:10',
            'type': 'Internal Sweep',
            'source_bank': 'Node #12 (Internal)',
            'dest_bank': 'Node #15 (Internal)',
            'amount': '-$2,100,000.00',
            'status': 'rollback'
        },
        {
            'date': '2023-10-28',
            'time': '10:05:44',
            'type': 'Wire Transfer',
            'source_bank': 'Morgan Stanley',
            'dest_bank': 'Node #12 (Internal)',
            'amount': '+$35,000,000.00',
            'status': 'successful'
        }
    ]

    banks = [
        {'name': 'JPMorgan Chase'},
        {'name': 'Goldman Sachs'},
        {'name': 'Morgan Stanley'},
        {'name': 'Citigroup'},
        {'name': 'Barclays PLC'}
    ]

    filters = {
        'date_range': 'Oct 1 - Oct 31, 2023'
    }

    user = get_user()
    return render_template('history.html',
                           user=user,
                           active_page='history',
                           transactions=transactions,
                           banks=banks,
                           filters=filters,
                           total_transactions=142)
@app.route('/banks')
def banks():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Datos dummy de los bancos (coherentes con la arquitectura distribuida)
    banks = {
        'peru': {
            'name': 'Perú Node',
            'status': 'active',
            'accounts': 14205,
            'volume': '$2.4M',
            'last_sync': '2s ago',
            'sync_status': 'recent'
        },
        'colombia': {
            'name': 'Colombia Node',
            'status': 'active',
            'accounts': 28910,
            'volume': '$5.1M',
            'last_sync': 'Just now',
            'sync_status': 'recent'
        },
        'chile': {
            'name': 'Chile Node',
            'status': 'inactive',  # Simula un nodo caído
            'accounts': 8450,
            'volume': None,
            'last_sync': '12m ago',
            'sync_status': 'delayed'
        }
    }

    coordinator = {
        'name': 'HQ Master',
        'status': 'Syncing active nodes'
    }

    user = get_user()
    return render_template('banks.html',
                           user=user,
                           active_page='banks',
                           banks=banks,
                           coordinator=coordinator)
    
@app.route('/monitoring')
def monitoring():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    # Datos dummy de monitoreo (luego se obtendrán de Prometheus/gRPC)
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
            {'name': 'Node-D', 'cpu': 95, 'color': '[#ef4444]'},
            {'name': 'Node-E', 'cpu': 30, 'color': '[#8b5cf6]'}
        ],
        'logs': [
            {'timestamp': '2023-10-27 14:32:01.442', 'level': 'INFO', 'message': 'Node-C initiated Bully Election (ID: 8492). Higher ID nodes pinged.'},
            {'timestamp': '2023-10-27 14:32:01.445', 'level': 'INFO', 'message': 'Node-D responded to Election ID: 8492. Node-C stands down.'},
            {'timestamp': '2023-10-27 14:32:01.450', 'level': 'SUCCESS', 'message': 'Node-D broadcasts Victory. New Coordinator established.'},
            {'timestamp': '2023-10-27 14:32:05.112', 'level': 'INFO', 'message': '2PC Phase 1: Prepare sent to 5 participants (TxID: 99xA4).'},
            {'timestamp': '2023-10-27 14:32:05.184', 'level': 'WARN', 'message': '2PC Latency spike detected on Node-B (72ms).'},
            {'timestamp': '2023-10-27 14:32:05.190', 'level': 'INFO', 'message': '2PC Phase 1: All participants returned VOTE_COMMIT.'},
            {'timestamp': '2023-10-27 14:32:05.195', 'level': 'INFO', 'message': '2PC Phase 2: Global COMMIT broadcast.'},
            {'timestamp': '2023-10-27 14:32:05.210', 'level': 'SUCCESS', 'message': 'Transaction 99xA4 finalized. Total latency: 98ms.'},
            {'timestamp': '2023-10-27 14:32:08.001', 'level': 'ERROR', 'message': 'Node-E unresponsive to heartbeat. Initiating timeout protocol.'}
        ]
    }
    
    user = get_user()
    return render_template('monitoring.html', user=user, active_page='monitoring', metrics=metrics)

@app.route('/coordination')
def coordination():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Datos dummy de coordinación (coherentes con Bully Algorithm)
    coordinator = {
        'name': 'Node #1 (Perú)',
        'short_name': 'N1',
        'details': 'ID: 10.24.1.101 • Region: South America',
        'state': 'STABLE'
    }

    nodes = [
        {'name': 'Node #1 (Perú)', 'short_name': 'N1', 'state': 'LEADER', 'priority': 100, 'uptime': '45d 12h', 'topology_x': '50%', 'topology_y': '50%'},
        {'name': 'Node #2 (Chile)', 'short_name': 'N2', 'state': 'FOLLOWER', 'priority': 80, 'uptime': '45d 11h', 'topology_x': '20%', 'topology_y': '20%'},
        {'name': 'Node #3 (Colombia)', 'short_name': 'N3', 'state': 'DISCONNECTED', 'priority': 90, 'uptime': '-', 'topology_x': '75%', 'topology_y': '75%'},
        {'name': 'Node #4', 'short_name': 'N4', 'state': 'FOLLOWER', 'priority': 75, 'uptime': '12d 04h', 'topology_x': '80%', 'topology_y': '30%'},
        {'name': 'Node #5', 'short_name': 'N5', 'state': 'FOLLOWER', 'priority': 60, 'uptime': '05d 18h', 'topology_x': '25%', 'topology_y': '80%'}
    ]

    events = [
        {'type': 'election', 'time': 'Just now', 'title': 'New Leader Elected: Node #1', 'description': 'Algorithm stabilized. Broadcast sent.'},
        {'type': 'election', 'time': '2 mins ago', 'title': 'Election Started', 'description': 'Initiated by Node #2 due to timeout.'},
        {'type': 'failure', 'time': '2 mins ago', 'title': 'Node #3 Disconnected', 'description': 'Heartbeat failed after 3 retries.'},
        {'type': 'sync', 'time': '1 hr ago', 'title': 'Routine Sync Completed', 'description': 'All 5 nodes acknowledged.'}
    ]

    user = get_user()
    return render_template('coordination.html',
                           user=user,
                           active_page='coordination',
                           coordinator=coordinator,
                           nodes=nodes,
                           events=events)

@app.route('/error', endpoint='error')
def error_page():
    # Esta vista puede recibir parámetros por query string para simular distintos fallos
    error_info = request.args.get('info', 'disconnection')

    # Datos dummy del estado de recuperación
    recovery = {
        'status_message': 'AUTOMATIC RECOVERY IN PROGRESS',
        'trigger': 'Timeout Threshold Reached',
        'rollback_id': 'RBK-992-A',
        'routine': 'Synchronizing Ledger',
        'eta': '~15s',
        'button_text': 'Retry Connection'
    }

    failed_node = {
        'name': 'Node #3 (Colombia)',
        'status': 'Disconnected',
        'last_ping': '42s ago'
    }

    user = get_user() if 'user' in session else None
    return render_template('error.html',
                           user=user,
                           active_page='error',
                           recovery=recovery,
                           failed_node=failed_node,
                           error_title='System state restoring',
                           error_message='The coordinator detected a disruption in the network topology. A rollback was executed to maintain ledger integrity, and automatic reconciliation is underway.')
   
def get_user():
    return {
        'name': session.get('user', 'Admin'),
        'bank_name': 'Global Finance',
        'role': 'Institutional Node #12',
        'avatar_url': 'https://ui-avatars.com/api/?name=Admin&background=316bf3&color=fff'
    }
if __name__ == '__main__':
    app.run(debug=True)
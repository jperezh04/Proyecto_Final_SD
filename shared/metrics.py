from prometheus_client import Counter, Histogram, Gauge


def create_metrics(node_label):
    tx_counter = Counter(
        "bank_transactions_total",
        "Total de transacciones procesadas",
        ["node", "type"],
    )
    twopc_duration = Histogram(
        "bank_2pc_duration_seconds",
        "Duración de las fases del 2PC",
        ["node", "phase"],
        buckets=[.001, .005, .01, .025, .05, .1, .25, .5, 1.0],
    )
    node_state_gauge = Gauge(
        "bank_node_state",
        "Estado del nodo: 1=LEADER, 0=FOLLOWER, -1=PAUSED",
        ["node"],
    )
    node_state_gauge.labels(node=node_label).set(0)

    return tx_counter, twopc_duration, node_state_gauge

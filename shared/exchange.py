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

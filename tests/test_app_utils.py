"""Unit tests for pure utility functions in flask-frontend/app.py."""

import os
import sys

import pytest

# Add flask-frontend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'flask-frontend'))

from app import (
    _convert_amount,
    _format_money,
    _client_display_name,
    _client_segment,
    _currency_totals,
    _estimated_usd,
    _log_local_event,
    _bank_from_node_label,
    get_balance_distribution,
    _validate_transfer_payload,
    local_event_log,
    EXCHANGE_RATES,
    app,
)


# ── _convert_amount ────────────────────────────────────────────────────────

class TestConvertAmount:
    def test_same_currency(self):
        amount, rate = _convert_amount(100, "PEN", "PEN")
        assert amount == 100.0
        assert rate == 1.0

    def test_pen_to_usd(self):
        amount, rate = _convert_amount(375, "PEN", "USD")
        assert amount == 100.0

    def test_usd_to_clp(self):
        amount, _ = _convert_amount(1, "USD", "CLP")
        assert amount == 950.0

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="Moneda no soportada"):
            _convert_amount(1, "USD", "EUR")

    def test_none_same(self):
        amount, rate = _convert_amount(10, None, None)
        assert amount == 10.0
        assert rate == 1.0


# ── _format_money ──────────────────────────────────────────────────────────

class TestFormatMoney:
    def test_basic(self):
        assert _format_money("USD", 1234.5) == "USD 1,234.50"

    def test_zero(self):
        assert _format_money("PEN", 0) == "PEN 0.00"

    def test_large_number(self):
        result = _format_money("COP", 1000000)
        assert "1,000,000.00" in result


# ── _client_display_name ───────────────────────────────────────────────────

class TestClientDisplayName:
    def test_known_user(self):
        assert _client_display_name("ana_peru_solo") == "Ana Torres"

    def test_known_user_valeria(self):
        assert _client_display_name("valeria_global") == "Valeria Global"

    def test_unknown_user_titlecase(self):
        assert _client_display_name("john_doe") == "John Doe"

    def test_none_input(self):
        result = _client_display_name(None)
        assert result == "Cliente Sin Nombre"

    def test_empty_string(self):
        result = _client_display_name("")
        assert result == "Cliente Sin Nombre"


# ── _client_segment ────────────────────────────────────────────────────────

class TestClientSegment:
    def test_local(self):
        assert _client_segment(1) == "Cliente local"

    def test_binational(self):
        assert _client_segment(2) == "Cliente binacional"

    def test_global(self):
        assert _client_segment(3) == "Cliente global"

    def test_more_than_three(self):
        assert _client_segment(5) == "Cliente global"


# ── _currency_totals ───────────────────────────────────────────────────────

class TestCurrencyTotals:
    def test_single_currency(self):
        accounts = [
            {"currency": "PEN", "numeric_balance": 100},
            {"currency": "PEN", "numeric_balance": 200},
        ]
        totals = _currency_totals(accounts)
        assert len(totals) == 1
        assert totals[0]["currency"] == "PEN"
        assert totals[0]["amount"] == 300

    def test_multiple_currencies(self):
        accounts = [
            {"currency": "PEN", "numeric_balance": 100},
            {"currency": "USD", "numeric_balance": 50},
        ]
        totals = _currency_totals(accounts)
        assert len(totals) == 2
        currencies = {t["currency"] for t in totals}
        assert currencies == {"PEN", "USD"}

    def test_empty_list(self):
        assert _currency_totals([]) == []

    def test_missing_currency_uses_dash(self):
        accounts = [{"numeric_balance": 10}]
        totals = _currency_totals(accounts)
        assert totals[0]["currency"] == "\u2014"


# ── _estimated_usd ─────────────────────────────────────────────────────────

class TestEstimatedUsd:
    def test_usd_passthrough(self):
        accounts = [{"currency": "USD", "numeric_balance": 100}]
        assert _estimated_usd(accounts) == 100.0

    def test_pen_conversion(self):
        accounts = [{"currency": "PEN", "numeric_balance": 375}]
        assert _estimated_usd(accounts) == 100.0

    def test_mixed_currencies(self):
        accounts = [
            {"currency": "USD", "numeric_balance": 100},
            {"currency": "PEN", "numeric_balance": 375},
        ]
        assert _estimated_usd(accounts) == 200.0

    def test_empty(self):
        assert _estimated_usd([]) == 0.0


# ── _log_local_event ───────────────────────────────────────────────────────

class TestLogLocalEvent:
    def test_appends_event(self):
        initial_len = len(local_event_log)
        _log_local_event("test", "Test Title", "Test Description")
        assert len(local_event_log) == initial_len + 1
        last = local_event_log[-1]
        assert last["type"] == "test"
        assert last["title"] == "Test Title"
        assert last["description"] == "Test Description"
        assert "timestamp" in last


# ── _bank_from_node_label ──────────────────────────────────────────────────

class TestBankFromNodeLabel:
    def test_node_hash_format(self):
        assert _bank_from_node_label("Node #3 (Peru)") == "peru"
        assert _bank_from_node_label("Node #2 (Chile)") == "chile"
        assert _bank_from_node_label("Node #1 (Colombia)") == "colombia"

    def test_nodo_hash_format(self):
        assert _bank_from_node_label("Nodo #3 (Perú)") == "peru"

    def test_short_format(self):
        assert _bank_from_node_label("N3") == "peru"
        assert _bank_from_node_label("N2") == "chile"
        assert _bank_from_node_label("N1") == "colombia"

    def test_none_returns_none(self):
        assert _bank_from_node_label(None) is None

    def test_empty_returns_none(self):
        assert _bank_from_node_label("") is None

    def test_unknown_returns_none(self):
        assert _bank_from_node_label("SomeRandomLabel") is None


# ── get_balance_distribution ───────────────────────────────────────────────

class TestGetBalanceDistribution:
    def test_basic_distribution(self):
        accounts = [
            {"bank_id": "peru", "numeric_balance": 1000},
            {"bank_id": "chile", "numeric_balance": 500},
            {"bank_id": "colombia", "numeric_balance": 250},
        ]
        heights = get_balance_distribution(accounts)
        assert len(heights) == 3
        assert max(heights) == 100

    def test_empty_accounts(self):
        heights = get_balance_distribution([])
        assert len(heights) == 3
        assert all(h == 0 for h in heights)

    def test_single_bank(self):
        accounts = [{"bank_id": "peru", "numeric_balance": 500}]
        heights = get_balance_distribution(accounts)
        assert heights[0] == 100  # peru is the first bank


# ── _validate_transfer_payload ─────────────────────────────────────────────

class TestValidateTransferPayload:
    def _mock_account_exists(self, monkeypatch):
        monkeypatch.setattr("app._account_exists_in_bank", lambda bank, aid: True)

    def test_missing_fields(self):
        payload, err = _validate_transfer_payload({})
        assert payload is None
        assert "Faltan campos" in err

    def test_invalid_bank(self, monkeypatch):
        self._mock_account_exists(monkeypatch)
        data = {
            "source_bank": "invalid_bank",
            "dest_bank": "chile",
            "source_account": "PE001",
            "dest_account": "CH001",
            "amount": "100",
        }
        payload, err = _validate_transfer_payload(data)
        assert payload is None
        assert "inválido" in err.lower()

    def test_non_numeric_amount(self, monkeypatch):
        self._mock_account_exists(monkeypatch)
        data = {
            "source_bank": "peru",
            "dest_bank": "chile",
            "source_account": "PE001",
            "dest_account": "CH001",
            "amount": "abc",
        }
        payload, err = _validate_transfer_payload(data)
        assert payload is None
        assert "numérico" in err.lower()

    def test_negative_amount(self, monkeypatch):
        self._mock_account_exists(monkeypatch)
        data = {
            "source_bank": "peru",
            "dest_bank": "chile",
            "source_account": "PE001",
            "dest_account": "CH001",
            "amount": "-10",
        }
        payload, err = _validate_transfer_payload(data)
        assert payload is None
        assert "mayor que cero" in err

    def test_same_account(self, monkeypatch):
        self._mock_account_exists(monkeypatch)
        data = {
            "source_bank": "peru",
            "dest_bank": "peru",
            "source_account": "PE001",
            "dest_account": "PE001",
            "amount": "100",
        }
        payload, err = _validate_transfer_payload(data)
        assert payload is None
        assert "distintas" in err

    def test_account_prefix_mismatch(self, monkeypatch):
        self._mock_account_exists(monkeypatch)
        data = {
            "source_bank": "peru",
            "dest_bank": "chile",
            "source_account": "CH001",  # wrong prefix for peru
            "dest_account": "CH002",
            "amount": "100",
        }
        payload, err = _validate_transfer_payload(data)
        assert payload is None
        assert "no pertenece" in err

    def test_valid_payload(self, monkeypatch):
        self._mock_account_exists(monkeypatch)
        data = {
            "source_bank": "peru",
            "dest_bank": "chile",
            "source_account": "PE001",
            "dest_account": "CH001",
            "amount": "100",
            "description": "Test transfer",
        }
        payload, err = _validate_transfer_payload(data)
        assert err is None
        assert payload["amount"] == 100.0
        assert payload["source_account"] == "PE001"
        assert payload["dest_account"] == "CH001"

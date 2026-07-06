"""Unit tests for flask-frontend/bank_client.py."""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'flask-frontend'))

from bank_client import (
    bank_from_account,
    _account_to_dict,
    _tx_to_dict,
    BANK_LABELS,
    BANK_PREFIXES,
)


# ── bank_from_account ─────────────────────────────────────────────────────

class TestBankFromAccount:
    def test_peru_prefix(self):
        assert bank_from_account("PE001") == "peru"

    def test_chile_prefix(self):
        assert bank_from_account("CH001") == "chile"

    def test_colombia_prefix(self):
        assert bank_from_account("CO001") == "colombia"

    def test_lowercase(self):
        assert bank_from_account("pe001") == "peru"

    def test_unknown_prefix(self):
        assert bank_from_account("XX001") is None

    def test_empty_string(self):
        assert bank_from_account("") is None

    def test_none(self):
        assert bank_from_account(None) is None


# ── _account_to_dict ───────────────────────────────────────────────────────

class TestAccountToDict:
    def _make_account_proto(self):
        acc = MagicMock()
        acc.account_id = "PE001"
        acc.owner = "ana_peru_solo"
        acc.balance = 1500.0
        acc.currency = "PEN"
        acc.type = "ahorro"
        acc.created_at = "2025-01-01T00:00:00"
        acc.updated_at = "2025-06-01T00:00:00"
        return acc

    def test_basic_fields(self):
        acc = self._make_account_proto()
        result = _account_to_dict("peru", acc)
        assert result["number"] == "PE001"
        assert result["owner"] == "ana_peru_solo"
        assert result["numeric_balance"] == 1500.0
        assert result["currency"] == "PEN"
        assert result["bank_id"] == "peru"
        assert result["bank"] == BANK_LABELS["peru"]
        assert result["status"] == "active"

    def test_type_capitalized(self):
        acc = self._make_account_proto()
        result = _account_to_dict("peru", acc)
        assert result["type"] == "Ahorro"

    def test_empty_type(self):
        acc = self._make_account_proto()
        acc.type = ""
        result = _account_to_dict("peru", acc)
        assert result["type"] == "Cuenta"

    def test_country_code(self):
        acc = self._make_account_proto()
        result = _account_to_dict("chile", acc)
        assert result["country_code"] == "CH"

    def test_balance_format(self):
        acc = self._make_account_proto()
        result = _account_to_dict("peru", acc)
        assert "PEN" in result["balance"]
        assert "1,500.00" in result["balance"]


# ── _tx_to_dict ────────────────────────────────────────────────────────────

class TestTxToDict:
    def _make_tx_proto(self):
        tx = MagicMock()
        tx.transaction_id = "tx-001"
        tx.timestamp = "2025-06-01T12:00:00"
        tx.type = "deposit"
        tx.source_account = ""
        tx.dest_account = "PE001"
        tx.amount = 500.0
        tx.currency = "PEN"
        tx.description = "Deposito"
        tx.status = "exitosa"
        tx.bank_id = "peru"
        return tx

    def test_basic_fields(self):
        tx = self._make_tx_proto()
        result = _tx_to_dict(tx)
        assert result["transaction_id"] == "tx-001"
        assert result["amount"] == 500.0
        assert result["bank_id"] == "peru"
        assert result["bank_label"] == BANK_LABELS["peru"]

    def test_infers_bank_from_source(self):
        tx = self._make_tx_proto()
        tx.bank_id = ""
        tx.source_account = "PE001"
        result = _tx_to_dict(tx)
        assert result["bank_id"] == "peru"

    def test_infers_bank_from_dest(self):
        tx = self._make_tx_proto()
        tx.bank_id = ""
        tx.source_account = ""
        tx.dest_account = "CH002"
        result = _tx_to_dict(tx)
        assert result["bank_id"] == "chile"

    def test_unknown_bank_fallback(self):
        tx = self._make_tx_proto()
        tx.bank_id = ""
        tx.source_account = ""
        tx.dest_account = ""
        result = _tx_to_dict(tx)
        assert result["bank_id"] == "desconocido"

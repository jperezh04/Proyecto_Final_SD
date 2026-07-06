"""Unit tests for the bank server utility functions.

All three bank servers (peru, chile, colombia) share the same utility logic.
We import the module once (which registers Prometheus metrics once) and redirect
the data directories per-test via monkeypatch.
"""

import json
import os
import sys
import tempfile

import pytest

# Add bank-peru to path so we can import its module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bank-peru'))

# Import the server module once; Prometheus metrics register only on first import.
import server as bank_server


@pytest.fixture(autouse=True)
def _redirect_data_dirs(tmp_path, monkeypatch):
    """Point all data directories to a fresh tmp_path for each test."""
    accounts_dir = str(tmp_path / "accounts")
    pending_dir = str(tmp_path / "pending")
    transactions_dir = str(tmp_path / "transactions")
    os.makedirs(accounts_dir, exist_ok=True)
    os.makedirs(pending_dir, exist_ok=True)
    os.makedirs(transactions_dir, exist_ok=True)
    monkeypatch.setattr(bank_server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(bank_server, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(bank_server, "PENDING_DIR", pending_dir)
    monkeypatch.setattr(bank_server, "TRANSACTIONS_DIR", transactions_dir)


# ── convert_amount ──────────────────────────────────────────────────────────

class TestConvertAmount:
    def test_same_currency(self):
        amount, rate = bank_server.convert_amount(100, "PEN", "PEN")
        assert amount == 100.0
        assert rate == 1.0

    def test_pen_to_usd(self):
        amount, rate = bank_server.convert_amount(375, "PEN", "USD")
        assert amount == 100.0
        assert round(rate, 6) == round(1.0 / 3.75, 6)

    def test_usd_to_clp(self):
        amount, rate = bank_server.convert_amount(1, "USD", "CLP")
        assert amount == 950.0
        assert rate == 950.0

    def test_pen_to_cop(self):
        amount, rate = bank_server.convert_amount(3.75, "PEN", "COP")
        assert amount == 4000.0

    def test_unsupported_currency_raises(self):
        with pytest.raises(ValueError, match="Moneda no soportada"):
            bank_server.convert_amount(100, "PEN", "EUR")

    def test_none_currencies_same(self):
        amount, rate = bank_server.convert_amount(50, None, None)
        assert amount == 50.0
        assert rate == 1.0

    def test_case_insensitive(self):
        amount, _ = bank_server.convert_amount(1, "usd", "clp")
        assert amount == 950.0

    def test_zero_amount(self):
        amount, rate = bank_server.convert_amount(0, "USD", "PEN")
        assert amount == 0.0


# ── load / save / list accounts ────────────────────────────────────────────

class TestAccountPersistence:
    def test_load_nonexistent_returns_none(self):
        assert bank_server.load_account("DOES_NOT_EXIST") is None

    def test_save_and_load(self):
        account = {"account_id": "PE001", "owner": "alice", "balance": 500, "currency": "PEN"}
        bank_server.save_account("PE001", account)
        loaded = bank_server.load_account("PE001")
        assert loaded == account

    def test_save_overwrites(self):
        bank_server.save_account("PE001", {"balance": 100})
        bank_server.save_account("PE001", {"balance": 200})
        assert bank_server.load_account("PE001")["balance"] == 200

    def test_list_accounts_empty(self):
        assert bank_server.list_accounts() == []

    def test_list_accounts_all(self):
        bank_server.save_account("PE001", {"account_id": "PE001", "owner": "alice", "balance": 10})
        bank_server.save_account("PE002", {"account_id": "PE002", "owner": "bob", "balance": 20})
        accounts = bank_server.list_accounts()
        assert len(accounts) == 2

    def test_list_accounts_filter_owner(self):
        bank_server.save_account("PE001", {"account_id": "PE001", "owner": "alice", "balance": 10})
        bank_server.save_account("PE002", {"account_id": "PE002", "owner": "bob", "balance": 20})
        accounts = bank_server.list_accounts(owner="alice")
        assert len(accounts) == 1
        assert accounts[0]["owner"] == "alice"

    def test_list_accounts_nonexistent_owner(self):
        bank_server.save_account("PE001", {"account_id": "PE001", "owner": "alice", "balance": 10})
        assert bank_server.list_accounts(owner="nobody") == []


# ── transactions ───────────────────────────────────────────────────────────

class TestTransactionPersistence:
    def test_save_and_list(self):
        tx_data = {
            "transaction_id": "tx1", "timestamp": "2025-01-01T00:00:00",
            "type": "deposit", "source_account": "", "dest_account": "PE001",
            "amount": 100, "currency": "PEN", "description": "test", "status": "exitosa"
        }
        bank_server.save_transaction("tx1", tx_data)
        txs = bank_server.list_transactions()
        assert len(txs) == 1
        assert txs[0]["transaction_id"] == "tx1"

    def test_list_by_account_id(self):
        bank_server.save_transaction("tx1", {
            "transaction_id": "tx1", "timestamp": "2025-01-01T00:00:01",
            "source_account": "PE001", "dest_account": "PE002"
        })
        bank_server.save_transaction("tx2", {
            "transaction_id": "tx2", "timestamp": "2025-01-01T00:00:02",
            "source_account": "PE003", "dest_account": "PE004"
        })
        assert len(bank_server.list_transactions("PE001")) == 1
        assert len(bank_server.list_transactions("PE004")) == 1
        assert len(bank_server.list_transactions("PE999")) == 0

    def test_list_sorted_descending(self):
        bank_server.save_transaction("tx_a", {"transaction_id": "tx_a", "timestamp": "2025-01-01T00:00:00"})
        bank_server.save_transaction("tx_b", {"transaction_id": "tx_b", "timestamp": "2025-06-01T00:00:00"})
        txs = bank_server.list_transactions()
        assert txs[0]["timestamp"] > txs[1]["timestamp"]


# ── pending ────────────────────────────────────────────────────────────────

class TestPendingPersistence:
    def test_save_and_remove(self):
        bank_server.save_pending("p1", {"account_id": "PE001", "amount": 50})
        path = os.path.join(bank_server.PENDING_DIR, "p1.json")
        assert os.path.exists(path)
        bank_server.remove_pending("p1")
        assert not os.path.exists(path)

    def test_remove_nonexistent_does_not_raise(self):
        bank_server.remove_pending("nonexistent")

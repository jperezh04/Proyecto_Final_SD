"""Unit tests for flask-frontend/two_phase_commit.py convert_amount."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'flask-frontend'))

from two_phase_commit import convert_amount, EXCHANGE_RATES


class TestConvertAmount:
    def test_same_currency(self):
        amount, rate = convert_amount(100, "PEN", "PEN")
        assert amount == 100.0
        assert rate == 1.0

    def test_usd_to_pen(self):
        amount, rate = convert_amount(100, "USD", "PEN")
        assert amount == 375.0
        assert rate == 3.75

    def test_pen_to_usd(self):
        amount, rate = convert_amount(375, "PEN", "USD")
        assert amount == 100.0

    def test_clp_to_cop(self):
        amount, _ = convert_amount(950, "CLP", "COP")
        assert amount == 4000.0

    def test_unsupported_source(self):
        with pytest.raises(ValueError, match="Moneda no soportada"):
            convert_amount(100, "GBP", "USD")

    def test_unsupported_dest(self):
        with pytest.raises(ValueError, match="Moneda no soportada"):
            convert_amount(100, "USD", "JPY")

    def test_none_currencies(self):
        amount, rate = convert_amount(50, None, None)
        assert amount == 50.0
        assert rate == 1.0

    def test_case_insensitive(self):
        amount, _ = convert_amount(1, "usd", "pen")
        assert amount == 3.75

    def test_zero_amount(self):
        amount, _ = convert_amount(0, "USD", "PEN")
        assert amount == 0.0

    def test_exchange_rate_consistency(self):
        _, rate = convert_amount(100, "PEN", "CLP")
        expected = EXCHANGE_RATES["CLP"] / EXCHANGE_RATES["PEN"]
        assert round(rate, 6) == round(expected, 6)

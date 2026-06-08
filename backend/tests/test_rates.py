from decimal import Decimal

from app.services.cash_flow.rates import effective_rate


def test_effective_rate_con_vat():
    assert effective_rate(Decimal("55.00"), True, Decimal("22.00")) == Decimal("67.10")


def test_effective_rate_sin_vat():
    assert effective_rate(Decimal("55.00"), False, Decimal("22.00")) == Decimal("55.00")


def test_effective_rate_none():
    assert effective_rate(None, True, Decimal("22.00")) is None
    assert effective_rate(None, True, None) is None

from decimal import Decimal

from app.services.cash_flow.interest import monthly_carry


def test_carry_overdue_when_minimum_unpaid():
    # pagó 74 < mínimo 93.93 -> mora 18.30; saldo 504.76; interés 504.76*0.183/12*1.35 = 10.39
    assert monthly_carry(Decimal("578.76"), Decimal("74"), Decimal("93.93"), Decimal("14.64"), Decimal("18.30")) == Decimal("515.15")


def test_carry_financing_when_minimum_paid():
    # saldo 800, pagó 200 >= mínimo 100 -> financiación 12%; interés 800*0.12/12*1.35 = 10.80
    assert monthly_carry(Decimal("1000"), Decimal("200"), Decimal("100"), Decimal("12"), Decimal("24")) == Decimal("810.80")


def test_carry_zero_when_settled():
    assert monthly_carry(Decimal("500"), Decimal("500"), Decimal("100"), Decimal("12"), Decimal("24")) == Decimal("0.00")


def test_carry_none_minimum_is_overdue():
    # minimum None -> mora 24%; saldo 800; interés 800*0.24/12*1.35 = 21.60
    assert monthly_carry(Decimal("1000"), Decimal("200"), None, Decimal("12"), Decimal("24")) == Decimal("821.60")

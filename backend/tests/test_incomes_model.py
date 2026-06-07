from datetime import date
from decimal import Decimal

from app.models.currency import Currency
from app.models.income import Income
from app.models.income_type import IncomeType
from app.models.user import User


def _seed_refs(db_session):
    """Siembra las referencias (currency UY, income_type, user) para un Income. Requiere seed_uy (country UY)."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    db_session.add(IncomeType(id=1, code="sueldo", name="Sueldo", visible=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    return user


def test_income_roundtrip_recurring(db_session, seed_uy):
    user = _seed_refs(db_session)
    income = Income(
        user_id=user.id,
        income_type_id=1,
        currency_id=1,
        amount=Decimal("45000.00"),
        description="Sueldo principal",
        is_monthly_recurring=True,
        payment_day=5,
        shift_weekends=False,
    )
    db_session.add(income)
    db_session.flush()
    db_session.refresh(income)

    assert income.id is not None
    assert income.amount == Decimal("45000.00")
    assert income.payment_day == 5
    assert income.first_income_date is None
    assert income.total_months is None
    assert income.deleted_at is None
    assert income.created_at is not None
    assert income.updated_at is not None


def test_income_roundtrip_fixed_term(db_session, seed_uy):
    user = _seed_refs(db_session)
    income = Income(
        user_id=user.id,
        income_type_id=1,
        currency_id=1,
        amount=Decimal("30000.00"),
        description="Freelance ocasional",
        is_monthly_recurring=False,
        first_income_date=date(2026, 7, 10),
        total_months=1,
        shift_weekends=True,
    )
    db_session.add(income)
    db_session.flush()
    db_session.refresh(income)

    assert income.first_income_date == date(2026, 7, 10)
    assert income.total_months == 1
    assert income.payment_day is None
    assert income.shift_weekends is True

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.financing import Financing
from app.models.user import User


def _user(db_session, client):
    client.post("/auth/register", json={"email": "u@b.com", "password": "12345678"})
    return db_session.execute(select(User)).scalars().all()[-1]


def test_insert_with_schedule(client, db_session, seed_uy_currency):
    user = _user(db_session, client)
    f = Financing(
        user_id=user.id, currency_id=1, description="Préstamo Itaú", principal_amount=Decimal("200000.00"),
        start_date=date(2026, 7, 1), installment_start_date=date(2026, 8, 1),
        installment_amount=Decimal("10500.00"), total_installments=24,
        financing_rate=Decimal("72.00"), overdue_rate=Decimal("85.00"), usage_preference="primera_opcion",
    )
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)
    assert f.rates_add_vat is True   # default
    assert f.total_installments == 24


def test_insert_without_schedule(client, db_session, seed_uy_currency):
    user = _user(db_session, client)
    f = Financing(
        user_id=user.id, currency_id=1, description="Mi viejo me presta", principal_amount=Decimal("50000.00"),
        usage_preference="si_necesario",
    )
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)
    assert f.installment_start_date is None
    assert f.financing_rate is None

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.currency import Currency
from app.models.user import User


def _seed(db_session):
    """Currency UY + un user. Requiere seed_uy (country UY)."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    return user


def test_cash_flow_entry_ingreso_roundtrip(db_session, seed_uy):
    user = _seed(db_session)
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=date(2026, 7, 5),
        is_income=True,
        amount=Decimal("45000.00"),
        currency_id=1,
        source_type="ingreso",
        source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.flush()
    db_session.refresh(entry)

    assert entry.id is not None
    assert entry.is_income is True
    assert entry.amount == Decimal("45000.00")
    # nullables que un ingreso no usa quedan en NULL
    assert entry.financing_rate is None
    assert entry.overdue_rate is None
    assert entry.issue_year is None
    assert entry.issue_month is None
    assert entry.minimum_payment is None
    assert entry.created_at is not None
    assert entry.updated_at is not None


def test_cash_flow_entry_event_date_nullable(db_session, seed_uy):
    user = _seed(db_session)
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=None,
        is_income=False,
        amount=Decimal("1000.00"),
        currency_id=1,
        source_type="deuda_abierta",
        source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.flush()
    db_session.refresh(entry)
    assert entry.event_date is None


def test_cash_flow_payment_roundtrip_real(db_session, seed_uy):
    user = _seed(db_session)
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=date(2026, 7, 5),
        is_income=True,
        amount=Decimal("45000.00"),
        currency_id=1,
        source_type="ingreso",
        source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.flush()

    payment = CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("45000.00"))
    db_session.add(payment)
    db_session.flush()
    db_session.refresh(payment)

    assert payment.id is not None
    # pago real: plan_id, planned_date y note opcionales en NULL
    assert payment.plan_id is None
    assert payment.planned_date is None
    assert payment.note is None
    assert payment.created_at is not None


def test_cash_flow_payment_cascade_on_entry_delete(db_session, seed_uy):
    user = _seed(db_session)
    entry = CashFlowEntry(
        user_id=user.id,
        event_date=date(2026, 7, 5),
        is_income=True,
        amount=Decimal("45000.00"),
        currency_id=1,
        source_type="ingreso",
        source_id=uuid.uuid4(),
    )
    db_session.add(entry)
    db_session.flush()
    payment = CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("100.00"))
    db_session.add(payment)
    db_session.flush()
    payment_id = payment.id

    # borrar la entry borra el payment por ON DELETE CASCADE (cascade de BD)
    db_session.delete(entry)
    db_session.flush()
    db_session.expire_all()  # descarta el identity map para forzar relectura desde la BD

    remaining = db_session.execute(
        select(CashFlowPayment).where(CashFlowPayment.id == payment_id)
    ).scalar_one_or_none()
    assert remaining is None

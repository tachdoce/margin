import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.user import User
from app.services.review.obligations import review_obligation


@pytest.fixture
def user(db_session, seed_uy_currency):
    db_session.flush()
    db_session.add(
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", visible=True)
    )
    db_session.flush()
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _deuda(db_session, user, **overrides):
    kwargs = dict(
        user_id=user.id,
        obligation_type_id=10,
                currency_id=1,
        amount=Decimal("5000.00"),
        is_monthly_recurring=False,
        due_day=10,
        first_due_date=date(2026, 7, 1),
        total_installments=12,
        financing_rate=None,
        overdue_rate=None,
        rates_add_vat=True,
        shift_weekends=False,
        is_closed=False,
        review_findings="[]",
        is_ready=False,
    )
    kwargs.update(overrides)
    o = Obligation(**kwargs)
    db_session.add(o)
    db_session.flush()
    return o


def test_sin_findings(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("50.00"), overdue_rate=Decimal("60.00"))
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.review_findings == "[]"
    assert o.is_ready is True
    assert o.reviewed_at is not None


def test_overdue_lower_than_financing(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("50.00"), overdue_rate=Decimal("30.00"))
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert "overdue_lower_than_financing" in json.loads(o.review_findings)
    assert o.is_ready is False


def test_rate_above_threshold(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("160.00"), overdue_rate=None)
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert json.loads(o.review_findings) == ["rate_above_threshold"]
    assert o.is_ready is False


def test_dos_reglas_ordenadas_sin_duplicados(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("200.00"), overdue_rate=Decimal("10.00"))
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    codes = json.loads(o.review_findings)
    assert codes == ["overdue_lower_than_financing", "rate_above_threshold"]
    assert o.is_ready is False


def test_tasas_null_sin_findings(db_session, user):
    o = _deuda(db_session, user, financing_rate=None, overdue_rate=None)
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.review_findings == "[]"
    assert o.is_ready is True


def test_overdue_lower_requiere_ambas(db_session, user):
    # solo financing con valor (overdue NULL) → no dispara overdue_lower ni rate_above
    o = _deuda(db_session, user, financing_rate=Decimal("50.00"), overdue_rate=None)
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.review_findings == "[]"
    assert o.is_ready is True


def test_reset_acknowledge_con_findings(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("200.00"))
    o.user_acknowledged_at = datetime.now(timezone.utc)
    db_session.flush()
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.user_acknowledged_at is None
    assert o.is_ready is False


def test_mantiene_acknowledge_sin_findings(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("50.00"), overdue_rate=Decimal("60.00"))
    ack = datetime.now(timezone.utc)
    o.user_acknowledged_at = ack
    db_session.flush()
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.user_acknowledged_at is not None


def test_review_findings_es_json_lista(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("200.00"), overdue_rate=Decimal("10.00"))
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    parsed = json.loads(o.review_findings)
    assert isinstance(parsed, list)
    assert all(isinstance(c, str) for c in parsed)


def test_is_closed_short_circuit(db_session, user):
    # tasas que normalmente dispararían findings, pero cerrada → short-circuit
    o = _deuda(db_session, user, financing_rate=Decimal("200.00"), overdue_rate=Decimal("10.00"),
               is_closed=True)
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.review_findings == "[]"
    assert o.is_ready is True

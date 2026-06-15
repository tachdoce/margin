from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.currency import Currency
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.user import User


@pytest.fixture
def refs(db_session, seed_uy_currency):
    """Siembra obligation_types (1 por kind) y un usuario. Devuelve el usuario."""
    db_session.add_all(
        [
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                           description="x", visible=True),
            ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                           description="x", visible=True),
            ObligationType(id=8, obligation_kind="deuda_abierta", code="informal", name="Informal",
                           description="x", visible=True),
        ]
    )
    db_session.flush()
    user = User(country_code="UY")
    db_session.add(user)
    db_session.flush()
    return user


def _base_kwargs(user):
    """Campos NOT NULL comunes a toda obligación."""
    return dict(
        user_id=user.id,
        currency_id=1,
        amount=Decimal("45000.00"),
        is_monthly_recurring=False,
        shift_weekends=False,
        rates_add_vat=True,
        is_closed=False,
        review_findings="[]",
        is_ready=False,
    )


def test_insert_gasto_recurrente(db_session, refs):
    user = refs
    o = Obligation(
        **_base_kwargs(user),
        obligation_type_id=1,
                due_day=5,
    )
    o.is_monthly_recurring = True  # _base_kwargs lo trae en False; lo sobrescribimos
    db_session.add(o)
    db_session.flush()
    db_session.refresh(o)
    assert o.id is not None
    assert o.due_day == 5
    assert o.created_at is not None


def test_insert_deuda_con_cronograma(db_session, refs):
    user = refs
    o = Obligation(
        **_base_kwargs(user),
        obligation_type_id=10,
                due_day=10,
        total_installments=12,
        first_due_date=date(2026, 8, 1),
        financing_rate=Decimal("3.50"),
        overdue_rate=Decimal("5.00"),
    )
    db_session.add(o)
    db_session.flush()
    db_session.refresh(o)
    assert o.total_installments == 12
    assert o.financing_rate == Decimal("3.50")


def test_insert_deuda_abierta(db_session, refs):
    user = refs
    o = Obligation(
        **_base_kwargs(user),
        obligation_type_id=8,
            )
    db_session.add(o)
    db_session.flush()
    db_session.refresh(o)
    assert o.first_due_date is None
    assert o.financing_rate is None


def test_invalid_obligation_type_fk(db_session, refs):
    user = refs
    o = Obligation(**_base_kwargs(user), obligation_type_id=999, )
    db_session.add(o)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_self_reference_origin(db_session, refs):
    user = refs
    parent = Obligation(**_base_kwargs(user), obligation_type_id=10, )
    db_session.add(parent)
    db_session.flush()
    child = Obligation(
        **_base_kwargs(user), obligation_type_id=10,         origin_obligation_id=parent.id,
    )
    db_session.add(child)
    db_session.flush()
    db_session.refresh(child)
    assert child.origin_obligation_id == parent.id


def test_not_null_amount(db_session, refs):
    user = refs
    kwargs = _base_kwargs(user)
    del kwargs["amount"]
    o = Obligation(**kwargs, obligation_type_id=1, )
    db_session.add(o)
    with pytest.raises(IntegrityError):
        db_session.flush()

from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.currency import Currency
from app.models.plan import Plan
from app.models.plan_movement import PlanMovement
from app.models.user import User


def _seed(db_session):
    """Currency UY + un user. Requiere seed_uy (country UY)."""
    db_session.add(Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True))
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    return user


def test_plan_roundtrip_sin_objetivo(db_session, seed_uy):
    user = _seed(db_session)
    plan = Plan(
        user_id=user.id,
        name="Mi plan actual",
        is_default=True,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0.00"),
        dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.flush()
    db_session.refresh(plan)

    assert plan.id is not None
    assert plan.is_default is True
    assert plan.goal_kind is None
    assert plan.goal_amount is None
    assert plan.goal_currency_id is None
    assert plan.created_at is not None
    assert plan.updated_at is not None


def test_plan_con_objetivo_y_movimiento_prestamo(db_session, seed_uy):
    user = _seed(db_session)
    plan = Plan(
        user_id=user.id,
        name="Plan ahorro",
        is_default=False,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("15000.00"),
        dial_currency_id=1,
        goal_kind="ahorro_total",
        goal_amount=Decimal("100000.00"),
        goal_currency_id=1,
    )
    db_session.add(plan)
    db_session.flush()

    mov = PlanMovement(
        plan_id=plan.id,
        kind="prestamo",
        currency_id=1,
        description="Préstamo Itaú",
        principal_amount=Decimal("50000.00"),
        start_date=date(2026, 8, 1),
        income_duration_months=1,
        installment_amount=Decimal("5000.00"),
        installment_start_date=date(2026, 9, 1),
        total_installments=12,
        financing_rate=Decimal("48.50"),
        overdue_rate=Decimal("60.00"),
        rates_add_vat=True,
    )
    db_session.add(mov)
    db_session.flush()
    db_session.refresh(mov)

    assert mov.id is not None
    assert mov.kind == "prestamo"
    assert mov.total_installments == 12
    assert mov.financing_rate == Decimal("48.50")
    assert plan.goal_kind == "ahorro_total"


def test_plan_movement_nullables(db_session, seed_uy):
    user = _seed(db_session)
    plan = Plan(
        user_id=user.id,
        name="P",
        is_default=False,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0.00"),
        dial_currency_id=1,
    )
    db_session.add(plan)
    db_session.flush()

    mov = PlanMovement(
        plan_id=plan.id,
        kind="deuda_informal",
        currency_id=1,
        principal_amount=Decimal("3000.00"),
        start_date=date(2026, 7, 1),
        rates_add_vat=True,
    )
    db_session.add(mov)
    db_session.flush()
    db_session.refresh(mov)

    assert mov.description is None
    assert mov.income_duration_months is None
    assert mov.installment_amount is None
    assert mov.installment_start_date is None
    assert mov.total_installments is None
    assert mov.financing_rate is None
    assert mov.overdue_rate is None

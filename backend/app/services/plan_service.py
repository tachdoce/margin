from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.currency import Currency
from app.models.plan import Plan
from app.models.user import User

DEFAULT_PLAN_NAME = "Mi plan actual"


def create_default_plan(db: Session, user: User) -> Plan:
    """Crea el plan default del usuario (representa su realidad actual). No hace commit:
    la transacción la controla el caller (register_user)."""
    currency = db.execute(
        select(Currency).where(
            Currency.country_code == user.country_code,
            Currency.is_legal_tender.is_(True),
        )
    ).scalars().first()

    plan = Plan(
        user_id=user.id,
        name=DEFAULT_PLAN_NAME,
        is_default=True,
        is_engine_generated=False,
        selected_at=datetime.now(timezone.utc),
        dial_amount=Decimal("0"),
        dial_currency_id=currency.id,
        goal_kind=None,
        goal_amount=None,
        goal_currency_id=None,
    )
    db.add(plan)
    return plan

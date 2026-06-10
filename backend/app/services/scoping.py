from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.currency import Currency
from app.models.user import User

T = TypeVar("T")


def require_country_scoped(
    db: Session,
    user: User,
    model: type[T],
    entity_id,
    *,
    error: ErrorCode,
    field: str,
) -> T:
    """Devuelve la entidad `model` con `entity_id` si pertenece al país del usuario.

    Lanza AppError(error, field=field) si no existe o es de otro país.
    Convención: `model` debe exponer la columna `country_code`.
    """
    entity = db.get(model, entity_id) if entity_id is not None else None
    if entity is None or entity.country_code != user.country_code:
        raise AppError(error, field=field)
    return entity


def require_user_currency(db: Session, user: User, currency_id: int | None) -> Currency:
    """Valida que la moneda enviada por el usuario sea de su país."""
    return require_country_scoped(
        db, user, Currency, currency_id,
        error=ErrorCode.currency_not_available, field="currency_id",
    )


def legal_tender_currency(db: Session, user: User) -> Currency:
    """Moneda de curso legal del país del usuario (se deriva, no viene del body)."""
    return db.execute(
        select(Currency).where(
            Currency.country_code == user.country_code,
            Currency.is_legal_tender.is_(True),
        )
    ).scalars().first()


def credit_card_usd_currency(db: Session, user: User) -> Currency:
    """Moneda USD del país del usuario para tarjetas: allowed_in_credit_card y no de curso legal.
    Se deriva del catálogo (no del body)."""
    return db.execute(
        select(Currency).where(
            Currency.country_code == user.country_code,
            Currency.allowed_in_credit_card.is_(True),
            Currency.is_legal_tender.is_(False),
        )
    ).scalars().first()


def holdable_currencies(db: Session, user: User) -> list[Currency]:
    """Monedas que el usuario puede tener como efectivo: de su país y allowed_in_credit_card."""
    return list(
        db.execute(
            select(Currency)
            .where(Currency.country_code == user.country_code, Currency.allowed_in_credit_card.is_(True))
            .order_by(Currency.id)
        ).scalars()
    )


def require_holdable_currency(db: Session, user: User, currency_id: int | None) -> Currency:
    cur = db.get(Currency, currency_id) if currency_id is not None else None
    if cur is None or cur.country_code != user.country_code or not cur.allowed_in_credit_card:
        raise AppError(ErrorCode.currency_not_available, field="currency_id")
    return cur

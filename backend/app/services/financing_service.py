import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.financing import Financing
from app.models.user import User
from app.schemas.financing import FinancingCreate, FinancingUpdate
from app.services.scoping import require_user_currency

USAGE_PREFERENCES = ("primera_opcion", "si_necesario", "ultimo_recurso")

_EDITABLE = (
    "currency_id", "description", "principal_amount", "usage_preference", "start_date",
    "installment_start_date", "installment_amount", "total_installments", "financing_rate",
    "overdue_rate", "rates_add_vat",
)


def _validate_common(db, user, *, currency_id, description, principal_amount, usage_preference, installment_amount):
    require_user_currency(db, user, currency_id)  # 422 currency_not_available
    if description is None or len(description.strip()) < 8:
        raise AppError(ErrorCode.description_invalid, field="description")
    if principal_amount is None or principal_amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="principal_amount")
    if installment_amount is not None and installment_amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="installment_amount")
    if usage_preference not in USAGE_PREFERENCES:
        raise AppError(ErrorCode.usage_preference_invalid, field="usage_preference")


def _validate_schedule(isd, iamount, total, frate, orate):
    if isd is not None:
        if iamount is None:
            raise AppError(ErrorCode.installments_invalid, field="installment_amount")
        if total is None or total < 1:
            raise AppError(ErrorCode.installments_invalid, field="total_installments")
        for rate, field in ((frate, "financing_rate"), (orate, "overdue_rate")):
            if rate is not None and rate < 0:
                raise AppError(ErrorCode.rates_negative, field=field)
    else:
        for value, field in (
            (iamount, "installment_amount"), (total, "total_installments"),
            (frate, "financing_rate"), (orate, "overdue_rate"),
        ):
            if value is not None:
                raise AppError(ErrorCode.installments_invalid, field=field)


def create_financing(db: Session, user: User, payload: FinancingCreate) -> Financing:
    _validate_common(
        db, user, currency_id=payload.currency_id, description=payload.description,
        principal_amount=payload.principal_amount, usage_preference=payload.usage_preference,
        installment_amount=payload.installment_amount,
    )
    _validate_schedule(
        payload.installment_start_date, payload.installment_amount, payload.total_installments,
        payload.financing_rate, payload.overdue_rate,
    )
    f = Financing(
        user_id=user.id, currency_id=payload.currency_id, description=payload.description,
        principal_amount=payload.principal_amount, usage_preference=payload.usage_preference,
        start_date=payload.start_date, installment_start_date=payload.installment_start_date,
        installment_amount=payload.installment_amount, total_installments=payload.total_installments,
        financing_rate=payload.financing_rate, overdue_rate=payload.overdue_rate,
        rates_add_vat=payload.rates_add_vat,
    )
    db.add(f)
    db.flush()
    db.commit()
    db.refresh(f)
    return f


def list_financings(db: Session, user: User) -> list[Financing]:
    return list(
        db.execute(
            select(Financing).where(Financing.user_id == user.id).order_by(Financing.created_at.desc())
        ).scalars()
    )


def _require_financing(db: Session, user: User, financing_id: uuid.UUID) -> Financing:
    f = db.get(Financing, financing_id)
    if f is None or f.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return f


def update_financing(db: Session, user: User, financing_id: uuid.UUID, payload: FinancingUpdate) -> Financing:
    f = _require_financing(db, user, financing_id)
    fields = payload.model_fields_set
    if not fields & set(_EDITABLE):
        raise AppError(ErrorCode.empty_patch)

    def final(name):
        return getattr(payload, name) if name in fields else getattr(f, name)

    _validate_common(
        db, user, currency_id=final("currency_id"), description=final("description"),
        principal_amount=final("principal_amount"), usage_preference=final("usage_preference"),
        installment_amount=final("installment_amount"),
    )
    _validate_schedule(
        final("installment_start_date"), final("installment_amount"), final("total_installments"),
        final("financing_rate"), final("overdue_rate"),
    )
    for name in fields & set(_EDITABLE):
        setattr(f, name, getattr(payload, name))
    db.flush()
    db.commit()
    db.refresh(f)
    return f


def delete_financing(db: Session, user: User, financing_id: uuid.UUID) -> None:
    f = _require_financing(db, user, financing_id)
    db.delete(f)
    db.commit()

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.priority_level import PriorityLevel

MIN_DESCRIPTION_LENGTH = 3
SYSTEM_PRIORITY_LEVEL = 1  # Ineludible: solo lo asigna el sistema


def validate_priority(db: Session, priority_level: int | None) -> None:
    if (
        priority_level is None
        or priority_level == SYSTEM_PRIORITY_LEVEL
        or db.get(PriorityLevel, priority_level) is None
    ):
        raise AppError(ErrorCode.priority_level_invalid, field="priority_level")


def validate_description(description: str | None) -> str:
    cleaned = (description or "").strip()
    if len(cleaned) < MIN_DESCRIPTION_LENGTH:
        raise AppError(ErrorCode.description_invalid, field="description")
    return cleaned


def validate_amount(amount) -> None:
    if amount is None or amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")


def validate_due_day(due_day: int | None) -> None:
    if due_day is not None and not (1 <= due_day <= 31):
        raise AppError(ErrorCode.due_day_invalid, field="due_day")

from app.core.errors import AppError, ErrorCode

MIN_DESCRIPTION_LENGTH = 3


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


PAYMENT_RULES_DEBT = ("ninguno", "minimo", "total")
PAYMENT_RULES_OPEN = ("ninguno", "mensual")


def _validate_priority_rule(payment_rule: str, priority, *, allowed) -> None:
    if payment_rule not in allowed:
        raise AppError(ErrorCode.payment_rule_invalid, field="payment_rule")
    # ninguno ⟺ sin priority
    if (payment_rule == "ninguno") != (priority is None):
        raise AppError(ErrorCode.payment_rule_invalid, field="priority")


def validate_payment_config(
    kind: str, *, payment_rule, priority, monthly_paydown_amount, priority_open_debt
) -> None:
    """Valida la combinación final de campos de prioridad según el tipo de deuda/tarjeta.
    kind: 'deuda' (también tarjeta) | 'deuda_abierta'."""
    if kind == "deuda_abierta":
        if payment_rule not in PAYMENT_RULES_OPEN:
            raise AppError(ErrorCode.payment_rule_invalid, field="payment_rule")
        if priority is not None:
            raise AppError(ErrorCode.payment_rule_invalid, field="priority")
        if payment_rule == "mensual":
            if monthly_paydown_amount is None or monthly_paydown_amount <= 0:
                raise AppError(ErrorCode.amount_invalid, field="monthly_paydown_amount")
        elif monthly_paydown_amount is not None:
            raise AppError(ErrorCode.payment_rule_invalid, field="monthly_paydown_amount")
    else:  # 'deuda' y tarjeta
        _validate_priority_rule(payment_rule, priority, allowed=PAYMENT_RULES_DEBT)
        if monthly_paydown_amount is not None or priority_open_debt is not None:
            raise AppError(ErrorCode.payment_rule_invalid, field="payment_rule")

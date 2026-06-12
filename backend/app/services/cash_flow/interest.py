from decimal import ROUND_HALF_UP, Decimal

from app.services.cash_flow.constants import HIDDEN_COST_FACTOR

Q = Decimal("0.01")


def _raw_interest(amount, payment, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """Interés (sin cuantizar) del saldo impago. 0 si está saldado.
    Financiación si el pago alcanzó el mínimo, mora si no."""
    balance = amount - payment
    if balance <= 0:
        return Decimal("0")
    paid_minimum = minimum_payment is not None and payment >= minimum_payment
    rate = financing_rate if paid_minimum else overdue_rate
    return balance * (rate / Decimal("100")) / Decimal("12") * HIDDEN_COST_FACTOR


def monthly_carry(amount, payment, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """Saldo impago + interés a arrastrar al mes siguiente (misma moneda). 0 si está saldado.

    Provisional: evolucionará. Tasa de financiación si el pago alcanzó el mínimo, mora si no.
    """
    balance = amount - payment
    if balance <= 0:
        return Decimal("0.00")
    interest = _raw_interest(amount, payment, minimum_payment, financing_rate, overdue_rate)
    return (balance + interest).quantize(Q, rounding=ROUND_HALF_UP)


def monthly_interest(amount, payment, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """El interés que el carry suma al mes siguiente, cuantizado (misma moneda). 0 si saldado."""
    return _raw_interest(amount, payment, minimum_payment, financing_rate, overdue_rate).quantize(
        Q, rounding=ROUND_HALF_UP
    )

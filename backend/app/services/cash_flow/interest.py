from decimal import ROUND_HALF_UP, Decimal

from app.services.cash_flow.constants import HIDDEN_COST_FACTOR


def monthly_carry(amount, payment, minimum_payment, financing_rate, overdue_rate) -> Decimal:
    """Saldo impago + interés a arrastrar al mes siguiente (misma moneda). 0 si está saldado.

    Provisional: evolucionará. Tasa de financiación si el pago alcanzó el mínimo, mora si no.
    """
    balance = amount - payment
    if balance <= 0:
        return Decimal("0.00")
    paid_minimum = minimum_payment is not None and payment >= minimum_payment
    rate = financing_rate if paid_minimum else overdue_rate
    interest = balance * (rate / Decimal("100")) / Decimal("12") * HIDDEN_COST_FACTOR
    return (balance + interest).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

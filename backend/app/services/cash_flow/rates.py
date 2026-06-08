from decimal import ROUND_HALF_UP, Decimal


def effective_rate(rate: Decimal | None, rates_add_vat: bool, vat_rate: Decimal | None) -> Decimal | None:
    """Tasa efectiva con el IVA ya resuelto. NULL → NULL. Si rates_add_vat: rate × (1 + vat_rate/100),
    cuantizada a 2 decimales (ROUND_HALF_UP)."""
    if rate is None:
        return None
    if rates_add_vat:
        rate = rate * (Decimal(1) + vat_rate / Decimal(100))
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

from decimal import Decimal

# Mínimo de pago estimado para los meses PROYECTADOS de tarjeta (no hay resumen emitido): 15% del amount.
PROJECTED_MINIMUM_RATE = Decimal("0.15")

# Factor de gastos ocultos de tarjeta (provisional): infla el interés mensual.
HIDDEN_COST_FACTOR = Decimal("1.35")

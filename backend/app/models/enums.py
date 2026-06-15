from sqlalchemy import Enum

# Enum Postgres compartido por obligations y credit_cards (un solo objeto = se crea una vez).
PAYMENT_RULE = Enum("ninguno", "minimo", "total", "mensual", name="payment_rule")

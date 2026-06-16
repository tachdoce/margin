from app.core.config import settings
from app.core.security import hash_password


def test_hash_uses_configured_rounds():
    """El hash bcrypt embebe el cost como 3er segmento $: $2b$<NN>$...

    Verifica el mecanismo (el cost sale de settings), no mide tiempos.
    En entorno de test settings.bcrypt_rounds == 4, así que el segmento es "04".
    """
    h = hash_password("12345678")
    cost_segment = h.split("$")[2]
    assert cost_segment == f"{settings.bcrypt_rounds:02d}"

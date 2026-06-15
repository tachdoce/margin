from decimal import Decimal

import pytest

from app.core.errors import AppError, ErrorCode
from app.services.obligation_common import (
    validate_amount,
    validate_description,
    validate_due_day,
    validate_payment_config,
)


def test_payment_config_deuda_ok():
    validate_payment_config("deuda", payment_rule="minimo", priority=1,
                            monthly_paydown_amount=None, priority_open_debt=None)  # no levanta


def test_payment_config_deuda_ninguno_con_priority_rechaza():
    with pytest.raises(AppError) as e:
        validate_payment_config("deuda", payment_rule="ninguno", priority=1,
                                monthly_paydown_amount=None, priority_open_debt=None)
    assert e.value.code == ErrorCode.payment_rule_invalid


def test_payment_config_deuda_regla_invalida():
    with pytest.raises(AppError) as e:
        validate_payment_config("deuda", payment_rule="mensual", priority=1,
                                monthly_paydown_amount=None, priority_open_debt=None)
    assert e.value.code == ErrorCode.payment_rule_invalid


def test_payment_config_abierta_mensual_ok():
    validate_payment_config("deuda_abierta", payment_rule="mensual", priority=None,
                            monthly_paydown_amount=Decimal("2000"), priority_open_debt=3)


def test_payment_config_abierta_mensual_sin_monto_rechaza():
    with pytest.raises(AppError) as e:
        validate_payment_config("deuda_abierta", payment_rule="mensual", priority=None,
                                monthly_paydown_amount=None, priority_open_debt=None)
    assert e.value.code == ErrorCode.amount_invalid


def test_payment_config_abierta_con_priority_rechaza():
    with pytest.raises(AppError) as e:
        validate_payment_config("deuda_abierta", payment_rule="ninguno", priority=2,
                                monthly_paydown_amount=None, priority_open_debt=None)
    assert e.value.code == ErrorCode.payment_rule_invalid


def test_validate_description_trims():
    assert validate_description("  Alquiler depto  ") == "Alquiler depto"


def test_validate_description_minima_3():
    # 3 caracteres (tras strip) ahora es válido
    assert validate_description("UTE") == "UTE"
    assert validate_description("  abc  ") == "abc"


def test_validate_description_corta():
    with pytest.raises(AppError) as e:
        validate_description("ab")
    assert e.value.code == ErrorCode.description_invalid


def test_validate_amount_ok():
    validate_amount(Decimal("1.00"))


def test_validate_amount_cero():
    with pytest.raises(AppError) as e:
        validate_amount(Decimal("0"))
    assert e.value.code == ErrorCode.amount_invalid


def test_validate_due_day_ok():
    validate_due_day(15)
    validate_due_day(None)


def test_validate_due_day_fuera_de_rango():
    with pytest.raises(AppError) as e:
        validate_due_day(40)
    assert e.value.code == ErrorCode.due_day_invalid

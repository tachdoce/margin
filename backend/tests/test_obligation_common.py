from decimal import Decimal

import pytest

from app.core.errors import AppError, ErrorCode
from app.models.priority_level import PriorityLevel
from app.services.obligation_common import (
    validate_amount,
    validate_description,
    validate_due_day,
    validate_priority,
)


@pytest.fixture
def priorities(db_session):
    db_session.add_all([
        PriorityLevel(level=1, name="Ineludible", description="x"),
        PriorityLevel(level=2, name="Esencial", description="x"),
    ])
    db_session.flush()


def test_validate_priority_ok(db_session, priorities):
    validate_priority(db_session, 2)  # no levanta


def test_validate_priority_sistema(db_session, priorities):
    with pytest.raises(AppError) as e:
        validate_priority(db_session, 1)
    assert e.value.code == ErrorCode.priority_level_invalid


def test_validate_priority_inexistente(db_session, priorities):
    with pytest.raises(AppError):
        validate_priority(db_session, 999)


def test_validate_priority_none(db_session, priorities):
    with pytest.raises(AppError):
        validate_priority(db_session, None)


def test_validate_description_trims():
    assert validate_description("  Alquiler depto  ") == "Alquiler depto"


def test_validate_description_corta():
    with pytest.raises(AppError) as e:
        validate_description("corta")
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

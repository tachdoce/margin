from decimal import Decimal

import pytest

from app.core.errors import AppError, ErrorCode
from app.models.country import Country
from app.models.currency import Currency
from app.models.user import User
from app.services.scoping import (
    legal_tender_currency,
    require_country_scoped,
    require_user_currency,
)

UY_CURRENCY_ID = 1  # creada por la fixture seed_uy_currency


def _user(db_session, country_code="UY"):
    user = User(country_code=country_code)
    db_session.add(user)
    db_session.flush()
    return user


def _other_country_currency(db_session):
    """Currency de un país distinto a UY, para los casos negativos."""
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    db_session.flush()
    currency = Currency(
        id=2,
        country_code="AR",
        name="Peso argentino",
        is_legal_tender=True,
        allowed_in_credit_card=False,
    )
    db_session.add(currency)
    db_session.flush()
    return currency


def test_require_country_scoped_returns_entity_of_user_country(
    db_session, seed_uy_currency
):
    user = _user(db_session)
    result = require_country_scoped(
        db_session, user, Currency, UY_CURRENCY_ID,
        error=ErrorCode.currency_not_available, field="currency_id",
    )
    assert result.id == UY_CURRENCY_ID


def test_require_country_scoped_raises_for_other_country(db_session, seed_uy_currency):
    user = _user(db_session)
    other = _other_country_currency(db_session)
    with pytest.raises(AppError) as exc:
        require_country_scoped(
            db_session, user, Currency, other.id,
            error=ErrorCode.currency_not_available, field="currency_id",
        )
    assert exc.value.code == ErrorCode.currency_not_available
    assert exc.value.field == "currency_id"


def test_require_country_scoped_raises_for_none_id(db_session, seed_uy_currency):
    user = _user(db_session)
    with pytest.raises(AppError):
        require_country_scoped(
            db_session, user, Currency, None,
            error=ErrorCode.currency_not_available, field="currency_id",
        )


def test_require_country_scoped_raises_for_missing_id(db_session, seed_uy_currency):
    user = _user(db_session)
    with pytest.raises(AppError):
        require_country_scoped(
            db_session, user, Currency, 999999,
            error=ErrorCode.currency_not_available, field="currency_id",
        )


def test_require_user_currency_returns_currency_of_country(db_session, seed_uy_currency):
    user = _user(db_session)
    result = require_user_currency(db_session, user, UY_CURRENCY_ID)
    assert result.id == UY_CURRENCY_ID


def test_require_user_currency_raises_for_other_country(db_session, seed_uy_currency):
    user = _user(db_session)
    other = _other_country_currency(db_session)
    with pytest.raises(AppError) as exc:
        require_user_currency(db_session, user, other.id)
    assert exc.value.code == ErrorCode.currency_not_available
    assert exc.value.field == "currency_id"


def test_legal_tender_currency_returns_country_legal_tender(db_session, seed_uy_currency):
    user = _user(db_session)
    result = legal_tender_currency(db_session, user)
    assert result.id == UY_CURRENCY_ID
    assert result.is_legal_tender is True

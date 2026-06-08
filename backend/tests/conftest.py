import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.db import Base, get_db
from app.main import app
from app import models as _models  # noqa: F401  (registra los modelos en Base.metadata)

test_engine = create_engine(settings.test_database_url)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


@pytest.fixture
def db_session() -> Session:
    """Sesión sobre margin_test; cada test corre en una transacción que se revierte."""
    Base.metadata.create_all(bind=test_engine)
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def seed_uy(db_session):
    from decimal import Decimal

    from app.models.country import Country

    db_session.add(Country(code="UY", name="Uruguay", visible=True, vat_rate=Decimal("22.00")))
    db_session.flush()


@pytest.fixture
def seed_uy_currency(db_session, seed_uy):
    from app.models.currency import Currency

    db_session.add(
        Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True)
    )
    db_session.flush()


@pytest.fixture
def seed_cc_refs(db_session, seed_uy_currency):
    """UY + Peso (id=1) + institución, red y tipo de ítem (id=1) + un usuario. Devuelve el usuario."""
    from app.models.credit_card_item_type import CreditCardItemType
    from app.models.credit_card_network import CreditCardNetwork
    from app.models.institution import Institution
    from app.models.user import User

    db_session.add_all(
        [
            Institution(id=1, country_code="UY", name="Scotiabank", visible=True),
            CreditCardNetwork(id=1, country_code="UY", code="amex", name="Amex"),
            CreditCardItemType(id=1, code="compra", name="Compra", description="x"),
        ]
    )
    db_session.flush()
    user = User(country_code="UY")
    db_session.add(user)
    db_session.flush()
    return user

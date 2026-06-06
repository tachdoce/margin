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

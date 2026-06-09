import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.credit_card import CreditCard
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.credit_card_statement import CreditCardStatement
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem
from app.models.user import User

from tests.test_credit_cards_model import _card_kwargs


@pytest.fixture
def cc_catalog(db_session, seed_uy_currency):
    db_session.add_all([
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True),
        Institution(id=1, country_code="UY", name="Scotiabank", visible=True),
        CreditCardNetwork(id=1, country_code="UY", code="amex", name="Amex"),
        CreditCardItemType(id=1, code="compra", name="Compra", description="x"),
        CreditCardItemType(id=2, code="interes", name="Interés", description="x"),
        CreditCardItemType(id=3, code="suscripcion", name="Suscripción", description="x"),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _user(db_session):
    return db_session.execute(select(User)).scalars().first()


def _seed_ready_staging(db_session, user, items=None, **madre_over):
    fields = dict(
        user_id=user.id, institution_id=1, card_network_id=1,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25), current_limit=Decimal("180000.00"),
        total_local=Decimal("7991.28"), total_usd=Decimal("65.35"),
        minimum_payment_local=Decimal("600.00"), minimum_payment_usd=Decimal("0.00"),
        financing_rate_local=Decimal("69.98"), overdue_rate_local=Decimal("81.27"),
        financing_rate_usd=Decimal("13.50"), overdue_rate_usd=Decimal("15.68"),
        rates_add_vat=True, review_findings="[]", is_ready=True,
    )
    fields.update(madre_over)
    madre = StagingCreditCard(**fields)
    db_session.add(madre)
    db_session.flush()
    if items is None:
        items = [dict(charge_date=date(2026, 2, 2), description="SPORTLINE", amount=Decimal("1997.50"),
                      currency_id=1, current_installment=3, total_installments=4, item_type_id=1)]
    for it in items:
        db_session.add(StagingCreditCardItem(staging_credit_card_id=madre.id, **it))
    db_session.flush()
    return madre


def _cards(db_session, user):
    return db_session.execute(select(CreditCard).where(CreditCard.user_id == user.id)).scalars().all()


def test_promote_new_card(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user)
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["review_findings"] == ["closing_day_inferred"]
    assert body["is_ready"] is False
    cards = _cards(db_session, user)
    assert len(cards) == 1
    card = cards[0]
    assert card.closing_day == 13
    st = db_session.execute(select(CreditCardStatement).where(CreditCardStatement.credit_card_id == card.id)).scalars().all()
    assert len(st) == 1 and (st[0].issue_year, st[0].issue_month) == (2026, 5)
    # staging borrado
    assert db_session.execute(select(StagingCreditCard)).scalars().all() == []
    # motor no materializó (is_ready false)
    assert db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_type == "tarjeta_credito")
    ).scalars().all() == []


def test_promote_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    assert client.post("/credit-card-statements/promote", json={}, headers=headers).status_code == 404


def test_promote_409_not_ready(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, is_ready=False, review_findings='["new_card"]')
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_not_ready"


def test_promote_409_incomplete_madre(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, closing_date=None)  # is_ready true pero falta closing_date
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_not_ready"


def test_promote_409_items_incomplete(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, items=[
        dict(charge_date=date(2026, 2, 2), description="X", amount=Decimal("1.00"),
             currency_id=1, current_installment=None, total_installments=None, item_type_id=None),  # falta tipo
    ])
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "items_incomplete"


def test_promote_409_rates_required_new_card(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, financing_rate_usd=None)  # tarjeta nueva, falta una tasa
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "rates_required_new_card"


def test_promote_409_period_exists(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=5,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user)  # mismo período 2026/5
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_period_exists"


def test_promote_409_period_not_after_last(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=6,
        closing_date=date(2026, 6, 13), due_date=date(2026, 6, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user)  # 2026/5, anterior al último 2026/6
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_period_not_after_last"


def test_promote_existing_ready_materializes(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))  # closing_day 13, is_ready False de fábrica
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=4,
        closing_date=date(2026, 4, 13), due_date=date(2026, 4, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user)  # 2026/5, closing_day 13 == card.closing_day
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["review_findings"] == []
    assert r.json()["is_ready"] is True
    entries = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_type == "tarjeta_credito")
    ).scalars().all()
    assert len(entries) >= 1  # el motor materializó


def test_promote_closing_day_changed(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))  # closing_day 13
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=4,
        closing_date=date(2026, 4, 13), due_date=date(2026, 4, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user, closing_date=date(2026, 5, 25))  # día 25 vs 13 -> dif 12
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.json()["review_findings"] == ["closing_day_changed"]
    assert r.json()["is_ready"] is False


def test_promote_identical_values_not_treated_as_new(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))  # created_at == updated_at (recién creada)
    db_session.add(card)
    db_session.flush()
    # staging con MISMOS current_limit/tasas que la tarjeta, período nuevo, mismo closing_day
    _seed_ready_staging(
        db_session, user,
        current_limit=Decimal("150000.00"),  # = _card_kwargs
        financing_rate_local=Decimal("69.98"), overdue_rate_local=Decimal("81.27"),
        financing_rate_usd=Decimal("13.50"), overdue_rate_usd=Decimal("15.68"), rates_add_vat=True,
    )
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert "closing_day_inferred" not in r.json()["review_findings"]  # no se la trató como nueva


def test_promote_reactivates_soft_deleted(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user), deleted_at=datetime(2026, 4, 1, tzinfo=timezone.utc))
    db_session.add(card)
    db_session.flush()
    _seed_ready_staging(db_session, user)
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 200
    db_session.refresh(card)
    assert card.deleted_at is None  # reactivada
    assert len(_cards(db_session, user)) == 1  # no se creó otra


def test_promote_rates_not_overwritten_on_update(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))  # financing_rate_local 69.98
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=4,
        closing_date=date(2026, 4, 13), due_date=date(2026, 4, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user, financing_rate_local=None)  # NULL no debe pisar
    client.post("/credit-card-statements/promote", json={}, headers=headers)
    db_session.refresh(card)
    assert card.financing_rate_local == Decimal("69.98")


def test_promote_purchases(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, items=[
        dict(charge_date=date(2026, 2, 2), description="HELADERA", amount=Decimal("100.00"),
             currency_id=1, current_installment=3, total_installments=12, item_type_id=1),  # cuotas -> purchase
        dict(charge_date=date(2026, 4, 29), description="GOOGLE", amount=Decimal("69.99"),
             currency_id=3, current_installment=None, total_installments=None, item_type_id=3),  # suscripción -> purchase
        dict(charge_date=date(2026, 5, 1), description="CAFE", amount=Decimal("5.00"),
             currency_id=1, current_installment=None, total_installments=None, item_type_id=1),  # un pago compra -> NO
    ])
    client.post("/credit-card-statements/promote", json={}, headers=headers)
    purchases = db_session.execute(select(CreditCardPurchase)).scalars().all()
    descs = {p.description for p in purchases}
    assert descs == {"HELADERA", "GOOGLE"}


def test_promote_401(client, cc_catalog):
    assert client.post("/credit-card-statements/promote", json={}).status_code == 401

from decimal import Decimal

from sqlalchemy import select

from app.models.cash_balance import CashBalance
from app.models.currency import Currency
from app.models.user import User


def _user(db_session, client):
    client.post("/auth/register", json={"email": "u@b.com", "password": "12345678"})
    return db_session.execute(select(User).order_by(User.created_at.desc())).scalars().all()[-1]


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_currencies(db_session):
    # seed_uy_currency ya sembró Peso(1, holdable). Sumar Dólar(3, holdable) y UI(4, NO holdable).
    db_session.add(Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True))
    db_session.add(Currency(id=4, country_code="UY", name="Unidad Indexada", is_legal_tender=False, allowed_in_credit_card=False))
    db_session.commit()


def test_insert_cash_balance(client, db_session, seed_uy_currency):
    user = _user(db_session, client)
    db_session.add(CashBalance(user_id=user.id, currency_id=1, amount=Decimal("15000.00")))
    db_session.commit()
    row = db_session.get(CashBalance, (user.id, 1))
    assert row.amount == Decimal("15000.00")


def test_get_lists_holdable_zero_default(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    rows = client.get("/cash-balances", headers=headers).json()
    assert rows == [{"currency_id": 1, "amount": "0.00"}, {"currency_id": 3, "amount": "0.00"}]  # sin UI(4)


def test_get_requires_auth(client, db_session, seed_uy_currency):
    assert client.get("/cash-balances").status_code == 401


def test_put_sets_multiple_atomic(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    body = {"balances": [{"currency_id": 1, "amount": "15000.00"}, {"currency_id": 3, "amount": "200.00"}]}
    r = client.put("/cash-balances", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json() == [{"currency_id": 1, "amount": "15000.00"}, {"currency_id": 3, "amount": "200.00"}]


def test_put_upsert_updates(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "100.00"}]}, headers=headers)
    client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "500.00"}]}, headers=headers)
    rows = client.get("/cash-balances", headers=headers).json()
    assert next(x for x in rows if x["currency_id"] == 1)["amount"] == "500.00"


def test_put_non_holdable(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    r = client.put("/cash-balances", json={"balances": [{"currency_id": 4, "amount": "10.00"}]}, headers=headers)
    assert r.json()["code"] == "currency_not_available"


def test_put_negative(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    r = client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "-5.00"}]}, headers=headers)
    assert r.json()["code"] == "amount_negative"


def test_put_zero_ok(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    r = client.put("/cash-balances", json={"balances": [{"currency_id": 1, "amount": "0"}]}, headers=headers)
    assert r.status_code == 200


def test_put_duplicate(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    body = {"balances": [{"currency_id": 1, "amount": "1.00"}, {"currency_id": 1, "amount": "2.00"}]}
    assert client.put("/cash-balances", json=body, headers=headers).json()["code"] == "duplicate_currency"


def test_put_atomic_nothing_applied_on_failure(client, db_session, seed_uy_currency):
    _seed_currencies(db_session)
    headers = _headers(client)
    # segunda entrada inválida (no holdable) → no se aplica ninguna
    body = {"balances": [{"currency_id": 1, "amount": "999.00"}, {"currency_id": 4, "amount": "10.00"}]}
    assert client.put("/cash-balances", json=body, headers=headers).status_code == 422
    rows = client.get("/cash-balances", headers=headers).json()
    assert next(x for x in rows if x["currency_id"] == 1)["amount"] == "0.00"  # Peso quedó en 0

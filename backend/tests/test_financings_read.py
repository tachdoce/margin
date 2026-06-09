from app.models.user import User


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


BASE = {
    "currency_id": 1, "description": "Mi viejo me presta", "principal_amount": "50000.00",
    "usage_preference": "si_necesario",
}


def test_list_empty(client, db_session, seed_uy_currency):
    assert client.get("/financings", headers=_headers(client)).json() == []


def test_list_orders_newest_first(client, db_session, seed_uy_currency):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from sqlalchemy import select

    from app.models.financing import Financing

    headers = _headers(client)
    user = db_session.execute(select(User)).scalars().all()[-1]
    # created_at explícitos: en el harness, now() empata ambos inserts de la misma transacción
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for desc, ts in (("Primera opción", base), ("Segunda opción", base + timedelta(hours=1))):
        db_session.add(Financing(
            user_id=user.id, currency_id=1, description=desc, principal_amount=Decimal("50000.00"),
            usage_preference="si_necesario", created_at=ts,
        ))
    db_session.commit()
    rows = client.get("/financings", headers=headers).json()
    assert [r["description"] for r in rows] == ["Segunda opción", "Primera opción"]


def test_list_only_own(client, db_session, seed_uy_currency):
    headers_a = _headers(client, email="a@b.com")
    client.post("/financings", json=BASE, headers=headers_a)
    headers_b = _headers(client, email="b@b.com")
    assert client.get("/financings", headers=headers_b).json() == []

from datetime import datetime, timezone

from sqlalchemy import select

from app.models.user import User


def _register(client, email="u@b.com", password="12345678"):
    return client.post("/auth/register", json={"email": email, "password": password})


def test_login_ok(client, seed_uy):
    _register(client)
    resp = client.post("/auth/login", json={"email": "u@b.com", "password": "12345678"})
    assert resp.status_code == 200
    assert resp.json()["token"]
    assert resp.json()["user"]["country_code"] == "UY"


def test_login_wrong_password(client, seed_uy):
    _register(client)
    resp = client.post("/auth/login", json={"email": "u@b.com", "password": "incorrecta"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "credentials_invalid"


def test_login_unknown_email(client, seed_uy):
    resp = client.post("/auth/login", json={"email": "nadie@b.com", "password": "12345678"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "credentials_invalid"


def test_login_soft_deleted_user(client, db_session, seed_uy):
    _register(client)
    user = db_session.execute(select(User)).scalars().one()
    user.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    resp = client.post("/auth/login", json={"email": "u@b.com", "password": "12345678"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "credentials_invalid"

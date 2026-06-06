from sqlalchemy import select

from app.models.auth_identity import AuthIdentity


def test_register_creates_user_and_returns_token(client, db_session, seed_uy):
    resp = client.post(
        "/auth/register",
        json={"email": "Juan@Example.com ", "password": "miclave123", "display_name": "Juan"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["country_code"] == "UY"
    assert body["user"]["display_name"] == "Juan"
    assert body["token"]

    # el response NO expone metadata interna del usuario
    assert "created_at" not in body["user"]
    assert "updated_at" not in body["user"]

    identity = db_session.execute(select(AuthIdentity)).scalars().one()
    assert identity.identifier == "juan@example.com"  # normalizado
    assert identity.password_hash != "miclave123"  # hasheado


def test_register_token_contains_user_id(client, seed_uy):
    resp = client.post("/auth/register", json={"email": "a@b.com", "password": "12345678"})
    from app.core.security import decode_access_token

    payload = decode_access_token(resp.json()["token"])
    assert payload["user_id"] == resp.json()["user"]["id"]


def test_register_rejects_invalid_email(client, seed_uy):
    resp = client.post("/auth/register", json={"email": "no-es-email", "password": "12345678"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "email_invalid"
    assert body["field"] == "email"


def test_register_rejects_short_password(client, seed_uy):
    resp = client.post("/auth/register", json={"email": "a@b.com", "password": "corta"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "password_too_short"


def test_register_rejects_duplicate_email(client, seed_uy):
    payload = {"email": "dup@b.com", "password": "12345678"}
    assert client.post("/auth/register", json=payload).status_code == 201
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 409
    assert resp.json()["code"] == "email_already_registered"


def test_register_missing_password_returns_validation_failed(client, seed_uy):
    resp = client.post("/auth/register", json={"email": "a@b.com"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_failed"
    assert "errors" in body

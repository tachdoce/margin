import uuid

from app.models.financing import Financing


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


BASE = {
    "currency_id": 1, "description": "Mi viejo me presta", "principal_amount": "50000.00",
    "usage_preference": "si_necesario",
}


def test_delete_ok(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = client.post("/financings", json=BASE, headers=headers).json()["id"]
    assert client.delete(f"/financings/{fid}", headers=headers).status_code == 204
    assert db_session.get(Financing, uuid.UUID(fid)) is None


def test_delete_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    assert client.delete(f"/financings/{uuid.uuid4()}", headers=headers).status_code == 404


def test_delete_other_user(client, db_session, seed_uy_currency):
    headers_a = _headers(client, email="a@b.com")
    fid = client.post("/financings", json=BASE, headers=headers_a).json()["id"]
    headers_b = _headers(client, email="b@b.com")
    assert client.delete(f"/financings/{fid}", headers=headers_b).status_code == 404

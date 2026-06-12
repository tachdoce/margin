from sqlalchemy import select

from app.models.user import User


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


WITH_SCHEDULE = {
    "currency_id": 1, "description": "Préstamo Itaú preaprobado", "principal_amount": "200000.00",
    "usage_preference": "primera_opcion", "start_date": "2026-07-01", "installment_start_date": "2026-08-01",
    "installment_amount": "10500.00", "total_installments": 24, "financing_rate": "72.00",
    "overdue_rate": "85.00", "rates_add_vat": True,
}
NO_SCHEDULE = {
    "currency_id": 1, "description": "Mi viejo me presta", "principal_amount": "50000.00",
    "usage_preference": "si_necesario", "start_date": None,
}


def test_create_with_schedule(client, db_session, seed_uy_currency):
    r = client.post("/financings", json=WITH_SCHEDULE, headers=_headers(client))
    assert r.status_code == 201
    body = r.json()
    assert body["total_installments"] == 24
    assert body["installment_amount"] == "10500.00"
    assert "created_at" not in body


def test_create_without_schedule(client, db_session, seed_uy_currency):
    r = client.post("/financings", json=NO_SCHEDULE, headers=_headers(client))
    assert r.status_code == 201
    assert r.json()["installment_start_date"] is None
    assert r.json()["rates_add_vat"] is True  # default


def test_currency_not_available(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "currency_id": 999}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "currency_not_available"


def test_description_invalid(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "description": "ab"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "description_invalid"


def test_description_minima_3(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "description": "UTE"}
    r = client.post("/financings", json=body, headers=_headers(client))
    assert r.status_code == 201


def test_amount_invalid(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "principal_amount": "0"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "amount_invalid"


def test_usage_preference_invalid(client, db_session, seed_uy_currency):
    body = {**NO_SCHEDULE, "usage_preference": "cuando_sea"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "usage_preference_invalid"


def test_schedule_missing_fields(client, db_session, seed_uy_currency):
    # installment_start_date sin installment_amount/total_installments
    body = {**NO_SCHEDULE, "installment_start_date": "2026-08-01"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "installments_invalid"


def test_schedule_total_lt_1(client, db_session, seed_uy_currency):
    body = {**WITH_SCHEDULE, "total_installments": 0}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "installments_invalid"


def test_schedule_columns_without_anchor(client, db_session, seed_uy_currency):
    # sin installment_start_date pero con una columna de cronograma
    body = {**NO_SCHEDULE, "financing_rate": "10.00"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "installments_invalid"


def test_rates_negative(client, db_session, seed_uy_currency):
    body = {**WITH_SCHEDULE, "financing_rate": "-1.00"}
    assert client.post("/financings", json=body, headers=_headers(client)).json()["code"] == "rates_negative"

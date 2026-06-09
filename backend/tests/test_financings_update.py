def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


WITH_SCHEDULE = {
    "currency_id": 1, "description": "Préstamo Itaú preaprobado", "principal_amount": "200000.00",
    "usage_preference": "primera_opcion", "installment_start_date": "2026-08-01",
    "installment_amount": "10500.00", "total_installments": 24, "financing_rate": "72.00", "overdue_rate": "85.00",
}
NO_SCHEDULE = {
    "currency_id": 1, "description": "Mi viejo me presta", "principal_amount": "50000.00",
    "usage_preference": "si_necesario",
}


def _create(client, headers, body):
    return client.post("/financings", json=body, headers=headers).json()["id"]


def test_patch_amount_and_description(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = _create(client, headers, WITH_SCHEDULE)
    r = client.patch(f"/financings/{fid}", json={"principal_amount": "220000.00", "installment_amount": "11200.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["principal_amount"] == "220000.00"
    assert r.json()["installment_amount"] == "11200.00"


def test_patch_add_schedule(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = _create(client, headers, NO_SCHEDULE)
    r = client.patch(
        f"/financings/{fid}",
        json={"installment_start_date": "2026-08-01", "installment_amount": "5000.00", "total_installments": 10},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["total_installments"] == 10


def test_patch_remove_schedule(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = _create(client, headers, WITH_SCHEDULE)
    r = client.patch(
        f"/financings/{fid}",
        json={"installment_start_date": None, "installment_amount": None, "total_installments": None,
              "financing_rate": None, "overdue_rate": None},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["installment_start_date"] is None
    assert r.json()["financing_rate"] is None


def test_patch_empty(client, db_session, seed_uy_currency):
    headers = _headers(client)
    fid = _create(client, headers, NO_SCHEDULE)
    assert client.patch(f"/financings/{fid}", json={}, headers=headers).json()["code"] == "empty_patch"


def test_patch_inconsistent_final_state(client, db_session, seed_uy_currency):
    # quitar el ancla pero dejar una columna del cronograma -> inconsistente
    headers = _headers(client)
    fid = _create(client, headers, WITH_SCHEDULE)
    r = client.patch(f"/financings/{fid}", json={"installment_start_date": None}, headers=headers)
    assert r.json()["code"] == "installments_invalid"


def test_patch_not_found(client, db_session, seed_uy_currency):
    import uuid
    headers = _headers(client)
    assert client.patch(f"/financings/{uuid.uuid4()}", json={"principal_amount": "1.00"}, headers=headers).status_code == 404

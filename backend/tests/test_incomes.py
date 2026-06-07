from decimal import Decimal

from sqlalchemy import select

from app.models.country import Country
from app.models.currency import Currency
from app.models.income import Income
from app.models.income_type import IncomeType


def _seed_refs(db_session):
    """income_types (visible + oculto) y currencies (UY válida + AR de otro país). Requiere seed_uy."""
    db_session.add(Country(code="AR", name="Argentina", visible=True, vat_rate=Decimal("21.00")))
    db_session.add_all([
        Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True),
        Currency(id=2, country_code="AR", name="Peso AR", is_legal_tender=True, allowed_in_credit_card=False),
        IncomeType(id=1, code="sueldo", name="Sueldo", visible=True),
        IncomeType(id=9, code="oculto", name="Oculto", visible=False),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _recurring_body(**over):
    body = {
        "income_type_id": 1,
        "currency_id": 1,
        "amount": "45000.00",
        "description": "Sueldo principal",
        "is_monthly_recurring": True,
        "payment_day": 5,
    }
    body.update(over)
    return body


def _fixed_body(**over):
    body = {
        "income_type_id": 1,
        "currency_id": 1,
        "amount": "30000.00",
        "description": "Freelance ocasional",
        "is_monthly_recurring": False,
        "first_income_date": "2026-07-10",
        "total_months": 1,
    }
    body.update(over)
    return body


def test_create_recurring(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(), headers=_auth(client))
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["is_deleted"] is False
    assert body["payment_day"] == 5
    assert body["first_income_date"] is None
    assert body["total_months"] is None
    assert body["amount"] == "45000.00"
    assert body["shift_weekends"] is False


def test_create_fixed_term(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_fixed_body(), headers=_auth(client))
    assert resp.status_code == 201
    body = resp.json()
    assert body["first_income_date"] == "2026-07-10"
    assert body["total_months"] == 1
    assert body["payment_day"] is None


def test_create_requires_auth(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body())
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_create_ignores_body_user_id(client, db_session, seed_uy):
    _seed_refs(db_session)
    fake = "00000000-0000-0000-0000-000000000000"
    resp = client.post("/incomes", json=_recurring_body(user_id=fake), headers=_auth(client))
    assert resp.status_code == 201
    income = db_session.execute(select(Income)).scalars().one()
    assert str(income.user_id) != fake


def test_create_income_type_invalid_hidden(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(income_type_id=9), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_type_invalid"


def test_create_income_type_invalid_missing(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(income_type_id=123), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_type_invalid"


def test_create_currency_not_available(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(currency_id=2), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "currency_not_available"


def test_create_description_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(description="corta"), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "description_invalid"


def test_create_amount_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(amount="0"), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_invalid"


def test_create_payment_day_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(payment_day=32), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "payment_day_invalid"


def test_create_recurring_requires_payment_day(client, db_session, seed_uy):
    _seed_refs(db_session)
    body = _recurring_body()
    del body["payment_day"]
    resp = client.post("/incomes", json=body, headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "recurring_income_requires_payment_day"


def test_create_fixed_requires_dates(client, db_session, seed_uy):
    _seed_refs(db_session)
    body = _fixed_body()
    del body["first_income_date"]
    del body["total_months"]
    resp = client.post("/incomes", json=body, headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "fixed_term_income_requires_dates"


def test_create_total_months_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_fixed_body(total_months=0), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "total_months_invalid"


def test_create_form_inconsistent_recurring_with_dates(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(first_income_date="2026-07-10"), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_form_inconsistent"


def test_create_form_inconsistent_fixed_with_payment_day(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_fixed_body(payment_day=5), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_form_inconsistent"


def _create_recurring(client, headers, **over):
    return client.post("/incomes", json=_recurring_body(**over), headers=headers).json()


def test_patch_payment_day(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"payment_day": 15}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["payment_day"] == 15


def test_patch_absent_field_untouched(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"payment_day": 10}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["description"] == "Sueldo principal"


def test_patch_convert_recurring_to_fixed(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(
        f"/incomes/{income['id']}",
        json={
            "is_monthly_recurring": False,
            "first_income_date": "2026-12-15",
            "total_months": 6,
            "payment_day": None,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_monthly_recurring"] is False
    assert body["payment_day"] is None
    assert body["first_income_date"] == "2026-12-15"
    assert body["total_months"] == 6


def test_patch_inconsistent_final_state(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"first_income_date": "2026-12-15"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "income_form_inconsistent"


def test_patch_not_found(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    resp = client.patch(
        "/incomes/00000000-0000-0000-0000-000000000000", json={"payment_day": 10}, headers=headers
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_patch_requires_auth(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.patch("/incomes/00000000-0000-0000-0000-000000000000", json={"payment_day": 10})
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_patch_amount_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"amount": "0"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_invalid"


def test_patch_other_users_income_not_found(client, db_session, seed_uy):
    _seed_refs(db_session)
    owner = _auth(client, email="owner@b.com")
    income = _create_recurring(client, owner)
    other = _auth(client, email="other@b.com")
    resp = client.patch(f"/incomes/{income['id']}", json={"payment_day": 10}, headers=other)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_patch_payment_day_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"payment_day": 32}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "payment_day_invalid"


def test_patch_null_on_non_nullable_amount(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"amount": None}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "field_not_nullable"


def test_patch_null_on_non_nullable_recurring_flag(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    resp = client.patch(f"/incomes/{income['id']}", json={"is_monthly_recurring": None}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "field_not_nullable"


def test_create_payment_day_zero_invalid(client, db_session, seed_uy):
    _seed_refs(db_session)
    resp = client.post("/incomes", json=_recurring_body(payment_day=0), headers=_auth(client))
    assert resp.status_code == 422
    assert resp.json()["code"] == "payment_day_invalid"

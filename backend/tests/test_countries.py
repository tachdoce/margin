from decimal import Decimal

from app.models.country import Country


def test_list_countries_returns_visible(client, db_session):
    db_session.add(Country(code="UY", name="Uruguay", visible=True, vat_rate=Decimal("22.00")))
    db_session.flush()

    response = client.get("/countries")

    assert response.status_code == 200
    data = response.json()
    uy = next(c for c in data if c["code"] == "UY")
    assert uy["name"] == "Uruguay"
    assert uy["visible"] is True
    assert Decimal(str(uy["vat_rate"])) == Decimal("22.00")

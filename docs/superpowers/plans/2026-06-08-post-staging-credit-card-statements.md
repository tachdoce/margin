# POST /credit-card-statements (carga a staging) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar `POST /credit-card-statements`: carga un resumen a staging (UPSERT madre por user +
borrar/recrear ítems), resuelve catálogos a id-o-NULL, hereda `item_type_id` de compras previas, corre el
reviewer, y responde 201 con la madre + ítems (cada uno con `missing_fields`).

**Architecture:** Router fino `credit_card_statements.py` → `credit_card_statement_service.create_staging_statement`
→ modelos. Schemas Pydantic lenient (request) + `missing_fields` derivado (response). Todo en una transacción;
reviewer (`review_staging_credit_card`, ya existe) como paso final antes del commit.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-post-staging-credit-card-statements-design.md`

**Branch:** `feat/post-credit-card-statements` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `app/schemas/credit_card_statement.py` | `StagingStatementCreate` (+ sub-modelos), `StagingStatementOut`, `StagingStatementItemOut` |
| `app/services/credit_card_statement_service.py` | `create_staging_statement` + resolución de catálogos + herencia |
| `app/routers/credit_card_statements.py` | `POST /credit-card-statements` |
| `app/main.py` | registrar el router |
| `tests/test_credit_card_statements.py` | tests de endpoint (vía `client` + token) |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/post-credit-card-statements
```

---

## Task 1: Schemas

**Files:**
- Create: `app/schemas/credit_card_statement.py`

- [ ] **Step 1: Escribir los schemas**

```python
# app/schemas/credit_card_statement.py
import json
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem


class GeneralData(BaseModel):
    issuer: str | None = None
    card_network: str | None = None
    closing_date: date | None = None
    due_date: date | None = None
    current_limit: Decimal | None = None


class PaymentSummary(BaseModel):
    total_local: Decimal | None = None
    total_usd: Decimal | None = None
    minimum_payment_local: Decimal | None = None
    minimum_payment_usd: Decimal | None = None


class ChargeIn(BaseModel):
    date: date | None = None
    description: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    current_installment: int | None = None
    total_installments: int | None = None


class AnnualEffectiveRates(BaseModel):
    vat_excluded: bool | None = None
    financing_rate_local_this_month: Decimal | None = None
    overdue_rate_local_this_month: Decimal | None = None
    financing_rate_usd_this_month: Decimal | None = None
    overdue_rate_usd_this_month: Decimal | None = None
    financing_rate_local_next_month: Decimal | None = None
    overdue_rate_local_next_month: Decimal | None = None
    financing_rate_usd_next_month: Decimal | None = None
    overdue_rate_usd_next_month: Decimal | None = None


class StagingStatementCreate(BaseModel):
    general_data: GeneralData = GeneralData()
    payment_summary: PaymentSummary = PaymentSummary()
    charges: list[ChargeIn] = []
    annual_effective_rates: AnnualEffectiveRates = AnnualEffectiveRates()
    # payments / others vienen en el payload pero no se declaran: Pydantic los ignora.


class StagingStatementItemOut(BaseModel):
    id: uuid.UUID
    charge_date: date | None
    description: str | None
    amount: Decimal | None
    currency_id: int | None
    current_installment: int | None
    total_installments: int | None
    item_type_id: int | None
    missing_fields: list[str]

    @classmethod
    def from_model(cls, it: StagingCreditCardItem) -> "StagingStatementItemOut":
        mf: list[str] = []
        if it.charge_date is None:
            mf.append("charge_date")
        if it.description is None:
            mf.append("description")
        if it.amount is None:
            mf.append("amount")
        if it.currency_id is None:
            mf.append("currency_id")
        ci, ti = it.current_installment, it.total_installments
        if (ci is None) != (ti is None):  # solo uno de los dos
            mf.append("current_installment" if ci is None else "total_installments")
        if it.item_type_id is None:
            mf.append("item_type_id")
        return cls(
            id=it.id,
            charge_date=it.charge_date,
            description=it.description,
            amount=it.amount,
            currency_id=it.currency_id,
            current_installment=it.current_installment,
            total_installments=it.total_installments,
            item_type_id=it.item_type_id,
            missing_fields=mf,
        )


class StagingStatementOut(BaseModel):
    id: uuid.UUID
    institution_id: int | None
    card_network_id: int | None
    closing_date: date | None
    due_date: date | None
    current_limit: Decimal | None
    total_local: Decimal | None
    total_usd: Decimal | None
    minimum_payment_local: Decimal | None
    minimum_payment_usd: Decimal | None
    financing_rate_local: Decimal | None
    overdue_rate_local: Decimal | None
    financing_rate_usd: Decimal | None
    overdue_rate_usd: Decimal | None
    rates_add_vat: bool | None
    review_findings: list[str]
    is_ready: bool
    items: list[StagingStatementItemOut]

    @classmethod
    def from_model(
        cls, m: StagingCreditCard, items: list[StagingCreditCardItem]
    ) -> "StagingStatementOut":
        return cls(
            id=m.id,
            institution_id=m.institution_id,
            card_network_id=m.card_network_id,
            closing_date=m.closing_date,
            due_date=m.due_date,
            current_limit=m.current_limit,
            total_local=m.total_local,
            total_usd=m.total_usd,
            minimum_payment_local=m.minimum_payment_local,
            minimum_payment_usd=m.minimum_payment_usd,
            financing_rate_local=m.financing_rate_local,
            overdue_rate_local=m.overdue_rate_local,
            financing_rate_usd=m.financing_rate_usd,
            overdue_rate_usd=m.overdue_rate_usd,
            rates_add_vat=m.rates_add_vat,
            review_findings=json.loads(m.review_findings),
            is_ready=m.is_ready,
            items=[StagingStatementItemOut.from_model(it) for it in items],
        )
```

---

## Task 2: Servicio + router + tests (TDD)

**Files:**
- Create: `app/services/credit_card_statement_service.py`
- Create: `app/routers/credit_card_statements.py`
- Modify: `app/main.py`
- Test: `tests/test_credit_card_statements.py`

- [ ] **Step 1: Escribir los tests (rojo)**

```python
# tests/test_credit_card_statements.py
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.credit_card import CreditCard
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.staging_credit_card import StagingCreditCard
from app.models.user import User

from tests.test_credit_cards_model import _card_kwargs

TODAY = date.today()
CLOSING = (TODAY - timedelta(days=5)).isoformat()
DUE = (TODAY + timedelta(days=10)).isoformat()


@pytest.fixture
def cc_catalog(db_session, seed_uy_currency):
    # seed_uy_currency siembra UY + Peso(1). Agregamos USD + emisor + red + tipos.
    db_session.add_all([
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True),
        Institution(id=1, country_code="UY", name="Scotiabank", visible=True),
        CreditCardNetwork(id=1, country_code="UY", code="amex", name="Amex"),
        CreditCardItemType(id=1, code="compra", name="Compra", description="x"),
        CreditCardItemType(id=3, code="suscripcion", name="Suscripción", description="x"),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _payload(**over):
    body = {
        "general_data": {
            "issuer": "Scotiabank", "card_network": "Amex",
            "closing_date": CLOSING, "due_date": DUE, "current_limit": 180000.00,
        },
        "payment_summary": {
            "total_local": 7991.28, "total_usd": 65.35,
            "minimum_payment_local": 600.00, "minimum_payment_usd": 0.00,
        },
        "charges": [
            {"date": "2026-02-02", "description": "SPORTLINE PUNTA", "amount": 1997.50,
             "currency": "Peso", "current_installment": 3, "total_installments": 4},
            {"date": "2026-04-29", "description": "GOOGLE *COM PULSO PULS", "amount": 69.99, "currency": "Dólar"},
        ],
        "payments": [], "others": [],
        "annual_effective_rates": {
            "vat_excluded": False,
            "financing_rate_local_this_month": 69.98, "overdue_rate_local_this_month": 81.27,
            "financing_rate_usd_this_month": 13.50, "overdue_rate_usd_this_month": 15.68,
            "financing_rate_local_next_month": 70.09, "overdue_rate_local_next_month": 81.39,
            "financing_rate_usd_next_month": 14.61, "overdue_rate_usd_next_month": 16.97,
        },
    }
    body.update(over)
    return body


def test_201_full_load(client, cc_catalog):
    headers = _auth(client)
    r = client.post("/credit-card-statements", json=_payload(), headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["institution_id"] == 1
    assert body["card_network_id"] == 1
    assert body["closing_date"] == CLOSING
    assert body["financing_rate_local"] == "70.09"   # COALESCE(next, this)
    assert body["rates_add_vat"] is True              # not vat_excluded
    items = body["items"]
    assert len(items) == 2
    by_cur = {it["currency_id"]: it for it in items}
    assert set(by_cur) == {1, 3}
    assert by_cur[1]["missing_fields"] == ["item_type_id"]
    assert by_cur[3]["missing_fields"] == ["item_type_id"]
    # reviewer corrió: sin tarjeta previa y emisor+red resueltos -> new_card
    assert body["review_findings"] == ["new_card"]
    assert body["is_ready"] is False


def test_resolution_to_null(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    p["general_data"]["issuer"] = "Banco Inexistente"
    p["general_data"]["card_network"] = "Nope"
    p["charges"][1]["currency"] = "Euro"
    r = client.post("/credit-card-statements", json=p, headers=headers)
    body = r.json()
    assert body["institution_id"] is None
    assert body["card_network_id"] is None
    google = next(it for it in body["items"] if it["description"].startswith("GOOGLE"))
    assert google["currency_id"] is None


def test_rates_fallback_to_this_month(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    p["annual_effective_rates"]["financing_rate_local_next_month"] = None
    r = client.post("/credit-card-statements", json=p, headers=headers)
    assert r.json()["financing_rate_local"] == "69.98"  # cae al this_month


def test_rates_both_null(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    p["annual_effective_rates"]["financing_rate_usd_next_month"] = None
    p["annual_effective_rates"]["financing_rate_usd_this_month"] = None
    r = client.post("/credit-card-statements", json=p, headers=headers)
    assert r.json()["financing_rate_usd"] is None


def test_rates_add_vat_absent_is_null(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    del p["annual_effective_rates"]["vat_excluded"]
    r = client.post("/credit-card-statements", json=p, headers=headers)
    assert r.json()["rates_add_vat"] is None


def test_upsert_overwrites(client, cc_catalog, db_session):
    headers = _auth(client)
    client.post("/credit-card-statements", json=_payload(), headers=headers)
    p2 = _payload()
    p2["charges"] = [{"date": "2026-03-03", "description": "OTRO", "amount": 10.0, "currency": "Peso"}]
    r = client.post("/credit-card-statements", json=p2, headers=headers)
    assert r.status_code == 201
    madres = db_session.execute(select(StagingCreditCard)).scalars().all()
    assert len(madres) == 1  # un solo staging por usuario
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["description"] == "OTRO"


def test_incomplete_item_missing_fields(client, cc_catalog):
    headers = _auth(client)
    p = _payload()
    p["charges"] = [{"description": "MERPAGO*ALGO", "current_installment": 2}]  # sin date/amount/currency, solo una cuota
    r = client.post("/credit-card-statements", json=p, headers=headers)
    mf = r.json()["items"][0]["missing_fields"]
    assert mf == ["charge_date", "amount", "currency_id", "total_installments", "item_type_id"]


def test_item_type_inheritance(client, cc_catalog, db_session):
    headers = _auth(client)
    user = db_session.execute(select(User)).scalars().first()
    card = CreditCard(**_card_kwargs(user))  # institución 1 + red 1
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardPurchase(
        credit_card_id=card.id, description="GOOGLE *COM PULSO PULS", charge_date=date(2026, 4, 29),
        amount=Decimal("69.99"), currency_id=3, total_installments=None, item_type_id=3,
        last_statement_closing_date=date(2026, 4, 13),
    ))
    db_session.flush()
    r = client.post("/credit-card-statements", json=_payload(), headers=headers)
    items = {it["description"]: it for it in r.json()["items"]}
    google = items["GOOGLE *COM PULSO PULS"]
    assert google["item_type_id"] == 3                 # heredado
    assert "item_type_id" not in google["missing_fields"]
    assert items["SPORTLINE PUNTA"]["item_type_id"] is None  # sin compra previa


def test_no_inheritance_without_resolved_card(client, cc_catalog, db_session):
    headers = _auth(client)
    user = db_session.execute(select(User)).scalars().first()
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardPurchase(
        credit_card_id=card.id, description="GOOGLE *COM PULSO PULS", charge_date=date(2026, 4, 29),
        amount=Decimal("69.99"), currency_id=3, total_installments=None, item_type_id=3,
        last_statement_closing_date=date(2026, 4, 13),
    ))
    db_session.flush()
    p = _payload()
    p["general_data"]["card_network"] = "Nope"  # red no resuelve -> no hay herencia
    r = client.post("/credit-card-statements", json=p, headers=headers)
    google = next(it for it in r.json()["items"] if it["description"].startswith("GOOGLE"))
    assert google["item_type_id"] is None


def test_401_without_token(client, cc_catalog):
    r = client.post("/credit-card-statements", json=_payload())
    assert r.status_code == 401
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statements.py -q
```

- [ ] **Step 3: Crear el servicio**

```python
# app/services/credit_card_statement_service.py
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.credit_card import CreditCard
from app.models.credit_card_network import CreditCardNetwork
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem
from app.models.user import User
from app.schemas.credit_card_statement import StagingStatementCreate
from app.services.review.staging_credit_cards import review_staging_credit_card


def _resolve_institution(db: Session, country_code: str, name: str | None) -> int | None:
    if not name:
        return None
    return db.execute(
        select(Institution.id).where(
            Institution.name == name, Institution.country_code == country_code
        )
    ).scalars().first()


def _resolve_network(db: Session, country_code: str, name: str | None) -> int | None:
    if not name:
        return None
    return db.execute(
        select(CreditCardNetwork.id).where(
            CreditCardNetwork.name == name, CreditCardNetwork.country_code == country_code
        )
    ).scalars().first()


def _resolve_currency(db: Session, country_code: str, name: str | None) -> int | None:
    if not name:
        return None
    return db.execute(
        select(Currency.id).where(
            Currency.name == name,
            Currency.country_code == country_code,
            Currency.allowed_in_credit_card.is_(True),
        )
    ).scalars().first()


def _coalesce(next_v, this_v):
    return next_v if next_v is not None else this_v


def _inherited_types(db: Session, user_id, institution_id: int, card_network_id: int) -> dict[str, int]:
    """{description: item_type_id más reciente} de las compras de la tarjeta del usuario."""
    rows = db.execute(
        select(
            CreditCardPurchase.description,
            CreditCardPurchase.item_type_id,
        )
        .join(CreditCard, CreditCard.id == CreditCardPurchase.credit_card_id)
        .where(
            CreditCard.user_id == user_id,
            CreditCard.institution_id == institution_id,
            CreditCard.card_network_id == card_network_id,
        )
        .order_by(CreditCardPurchase.last_statement_closing_date.desc())
    ).all()
    result: dict[str, int] = {}
    for description, item_type_id in rows:
        if description not in result:  # la primera (más reciente) gana
            result[description] = item_type_id
    return result


def create_staging_statement(
    db: Session, user: User, payload: StagingStatementCreate
) -> tuple[StagingCreditCard, list[StagingCreditCardItem]]:
    cc = user.country_code
    gd, ps, rates = payload.general_data, payload.payment_summary, payload.annual_effective_rates

    institution_id = _resolve_institution(db, cc, gd.issuer)
    card_network_id = _resolve_network(db, cc, gd.card_network)
    rates_add_vat = None if rates.vat_excluded is None else (not rates.vat_excluded)

    # UPSERT de la madre por user_id (UNIQUE)
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id).with_for_update()
    ).scalar_one_or_none()
    if madre is None:
        madre = StagingCreditCard(user_id=user.id)
        db.add(madre)

    madre.institution_id = institution_id
    madre.card_network_id = card_network_id
    madre.closing_date = gd.closing_date
    madre.due_date = gd.due_date
    madre.current_limit = gd.current_limit
    madre.total_local = ps.total_local
    madre.total_usd = ps.total_usd
    madre.minimum_payment_local = ps.minimum_payment_local
    madre.minimum_payment_usd = ps.minimum_payment_usd
    madre.financing_rate_local = _coalesce(
        rates.financing_rate_local_next_month, rates.financing_rate_local_this_month
    )
    madre.overdue_rate_local = _coalesce(
        rates.overdue_rate_local_next_month, rates.overdue_rate_local_this_month
    )
    madre.financing_rate_usd = _coalesce(
        rates.financing_rate_usd_next_month, rates.financing_rate_usd_this_month
    )
    madre.overdue_rate_usd = _coalesce(
        rates.overdue_rate_usd_next_month, rates.overdue_rate_usd_this_month
    )
    madre.rates_add_vat = rates_add_vat
    # reset del ciclo de revisión
    madre.reviewed_at = None
    madre.review_findings = "[]"
    madre.user_acknowledged_at = None
    madre.is_ready = False
    db.flush()  # asegura madre.id

    # borrar y recrear ítems
    db.execute(
        delete(StagingCreditCardItem).where(StagingCreditCardItem.staging_credit_card_id == madre.id)
    )

    inherited: dict[str, int] = {}
    if institution_id is not None and card_network_id is not None:
        inherited = _inherited_types(db, user.id, institution_id, card_network_id)

    items: list[StagingCreditCardItem] = []
    for ch in payload.charges:
        currency_id = _resolve_currency(db, cc, ch.currency)
        item_type_id = inherited.get(ch.description) if ch.description is not None else None
        item = StagingCreditCardItem(
            staging_credit_card_id=madre.id,
            charge_date=ch.date,
            description=ch.description,
            amount=ch.amount,
            currency_id=currency_id,
            current_installment=ch.current_installment,
            total_installments=ch.total_installments,
            item_type_id=item_type_id,
        )
        db.add(item)
        items.append(item)
    db.flush()

    review_staging_credit_card(db, madre.id)
    db.commit()
    db.refresh(madre)
    return madre, items
```

- [ ] **Step 4: Crear el router**

```python
# app/routers/credit_card_statements.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.credit_card_statement import StagingStatementCreate, StagingStatementOut
from app.services import credit_card_statement_service

router = APIRouter(tags=["credit-card-statements"])


@router.post(
    "/credit-card-statements", response_model=StagingStatementOut, status_code=status.HTTP_201_CREATED
)
def create_staging_statement(
    payload: StagingStatementCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StagingStatementOut:
    madre, items = credit_card_statement_service.create_staging_statement(db, user, payload)
    return StagingStatementOut.from_model(madre, items)
```

- [ ] **Step 5: Registrar el router en `app/main.py`**

Agregar `credit_card_statements` al import de routers y un `app.include_router(credit_card_statements.router)`
junto a los demás:

```python
from app.routers import (
    auth, bootstrap, countries, credit_card_statements, debts, expenses, health,
    incomes, obligations, plan_movements, plans,
)
...
app.include_router(credit_card_statements.router)
```

- [ ] **Step 6: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statements.py -q
```

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/credit_card_statement.py app/services/credit_card_statement_service.py app/routers/credit_card_statements.py app/main.py tests/test_credit_card_statements.py && git commit -m "feat: POST /credit-card-statements (carga a staging)"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (341 previos + los nuevos del endpoint).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/post-credit-card-statements` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** carga completa (resolución, tasas COALESCE, rates_add_vat, ítems + missing_fields),
  resolución a NULL, fallback de tasas, rates_add_vat ausente → NULL, UPSERT que pisa, ítem incompleto,
  herencia de tipo (con y sin tarjeta resuelta), reviewer corrió (new_card), 401. ✓
- **Sin placeholders:** schemas, servicio, router, registro y tests completos. ✓
- **Robustez temporal:** las fechas del payload (`CLOSING`/`DUE`) son relativas a hoy para que el reviewer no
  emita `due_date_in_future`/`due_date_too_old` y los asserts de findings sean deterministas en cualquier
  fecha de corrida. ✓
- **Consistencia:** `user_id` del token (nunca del body); `missing_fields` en orden de columna
  (charge_date, description, amount, currency_id, cuota faltante, item_type_id) — coincide con el ejemplo de
  Notion `["charge_date","amount","currency_id","total_installments","item_type_id"]`. ✓

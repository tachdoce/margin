# PUT /credit-card-statements (madre + ítem) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Agregar los dos PUT de staging: `PUT /credit-card-statements` (madre) y
`PUT /credit-card-statements/items/{item_id}` (ítem). Reemplazo total con validación de completitud y codes
específicos; el PUT madre re-corre el reviewer y hereda tipos al resolver la tarjeta.

**Architecture:** Crecen el router/servicio/schemas del recurso (`credit_card_statements.py`,
`credit_card_statement_service.py`, `credit_card_statement.py`). Schemas de update opcionales + validación de
negocio en el servicio. Refactor DRY: `StagingMadreOut` extraído, `StagingStatementOut(StagingMadreOut)`.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-put-staging-credit-card-statements-design.md`

**Branch:** `feat/put-credit-card-statements` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/put-credit-card-statements
```

---

## Task 1: Error codes nuevos

**Files:**
- Modify: `app/core/errors.py`

- [ ] **Step 1: Agregar 4 codes** después de `obligation_has_no_findings = (...)` (antes de `def __init__`):

```python
    card_network_invalid = (422, "Red de tarjeta no válida.")
    statement_incomplete = (422, "El resumen quedaría incompleto.")
    item_type_invalid = (422, "Tipo de ítem no válido.")
    item_incomplete = (422, "El ítem quedaría incompleto.")
```

---

## Task 2: Schemas (refactor + updates)

**Files:**
- Modify: `app/schemas/credit_card_statement.py`

- [ ] **Step 1: Reemplazar la clase `StagingStatementOut`** (el bloque actual completo) por `StagingMadreOut` +
  `StagingStatementOut(StagingMadreOut)`:

```python
class StagingMadreOut(BaseModel):
    id: uuid.UUID
    institution_id: int | None
    card_network_id: int | None
    closing_date: _date | None
    due_date: _date | None
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

    @classmethod
    def from_model(cls, m: StagingCreditCard) -> "StagingMadreOut":
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
        )


class StagingStatementOut(StagingMadreOut):
    items: list[StagingStatementItemOut]

    @classmethod
    def from_model(
        cls, m: StagingCreditCard, items: list[StagingCreditCardItem]
    ) -> "StagingStatementOut":
        base = StagingMadreOut.from_model(m)
        return cls(
            **base.model_dump(),
            items=[StagingStatementItemOut.from_model(it) for it in items],
        )
```

- [ ] **Step 2: Agregar los schemas de update** (al final del archivo):

```python
class StagingMadreUpdate(BaseModel):
    institution_id: int | None = None
    card_network_id: int | None = None
    closing_date: _date | None = None
    due_date: _date | None = None
    current_limit: Decimal | None = None
    total_local: Decimal | None = None
    total_usd: Decimal | None = None
    minimum_payment_local: Decimal | None = None
    minimum_payment_usd: Decimal | None = None
    financing_rate_local: Decimal | None = None
    overdue_rate_local: Decimal | None = None
    financing_rate_usd: Decimal | None = None
    overdue_rate_usd: Decimal | None = None
    rates_add_vat: bool | None = None


class StagingItemUpdate(BaseModel):
    charge_date: _date | None = None
    description: str | None = None
    amount: Decimal | None = None
    currency_id: int | None = None
    item_type_id: int | None = None
    current_installment: int | None = None
    total_installments: int | None = None
```

---

## Task 3: Servicio + router + tests (TDD)

**Files:**
- Modify: `app/services/credit_card_statement_service.py`
- Modify: `app/routers/credit_card_statements.py`
- Modify: `tests/test_credit_card_statements.py`

- [ ] **Step 1: Agregar los tests (rojo)** — extender `tests/test_credit_card_statements.py`.

Agregar a `cc_catalog` una moneda **no** admitida en tarjeta (para el caso `currency_not_available`):

```python
        Currency(id=4, country_code="UY", name="Unidad Indexada", is_legal_tender=False, allowed_in_credit_card=False),
```

Agregar el import del modelo de ítem (si no está) y los helpers + tests:

```python
from app.models.staging_credit_card_item import StagingCreditCardItem  # si no está ya


def _madre_body(**over):
    body = {
        "institution_id": 1, "card_network_id": 1,
        "closing_date": CLOSING, "due_date": DUE, "current_limit": 180000.00,
        "total_local": 7991.28, "total_usd": 65.35,
        "minimum_payment_local": 600.00, "minimum_payment_usd": 0.00,
        "financing_rate_local": 69.98, "overdue_rate_local": 81.27,
        "financing_rate_usd": 13.50, "overdue_rate_usd": 15.68,
        "rates_add_vat": True,
    }
    body.update(over)
    return body


def _item_body(**over):
    body = {
        "charge_date": "2026-05-03", "description": "MERPAGO*ALGO",
        "amount": 432.10, "currency_id": 1, "item_type_id": 1,
        "current_installment": 2, "total_installments": 6,
    }
    body.update(over)
    return body


def _post_staging(client, headers, **over):
    return client.post("/credit-card-statements", json=_payload(**over), headers=headers).json()


# ---- PUT madre ----

def test_put_madre_200(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(), headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["institution_id"] == 1
    assert body["total_local"] == "7991.28"
    assert "items" not in body  # respuesta madre-only
    assert isinstance(body["review_findings"], list)


def test_put_madre_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    r = client.put("/credit-card-statements", json=_madre_body(), headers=headers)
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_put_madre_statement_incomplete(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(total_local=None), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "statement_incomplete"


def test_put_madre_institution_invalid(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(institution_id=999), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "institution_invalid"


def test_put_madre_card_network_invalid(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(card_network_id=999), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "card_network_invalid"


def test_put_madre_amount_invalid(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(current_limit=0), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "amount_invalid"
    r2 = client.put("/credit-card-statements", json=_madre_body(total_local=-1), headers=headers)
    assert r2.json()["code"] == "amount_invalid"


def test_put_madre_rates_null_ok(client, cc_catalog):
    headers = _auth(client)
    _post_staging(client, headers)
    r = client.put("/credit-card-statements", json=_madre_body(
        financing_rate_local=None, overdue_rate_local=None,
        financing_rate_usd=None, overdue_rate_usd=None,
    ), headers=headers)
    assert r.status_code == 200
    assert r.json()["financing_rate_local"] is None


def test_put_madre_inheritance_on_resolve(client, cc_catalog, db_session):
    headers = _auth(client)
    # POST con emisor/red que NO resuelven -> institution/network NULL, GOOGLE item type NULL
    _post_staging(client, headers, general_data={
        "issuer": "Desconocido", "card_network": "Nope",
        "closing_date": CLOSING, "due_date": DUE, "current_limit": 180000.00,
    })
    # existe una tarjeta del usuario + una compra GOOGLE clasificada (tipo 3)
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
    # PUT resuelve emisor+red -> hereda el tipo a los ítems en NULL
    r = client.put("/credit-card-statements", json=_madre_body(), headers=headers)
    assert r.status_code == 200
    google = db_session.execute(
        select(StagingCreditCardItem).where(StagingCreditCardItem.description == "GOOGLE *COM PULSO PULS")
    ).scalars().first()
    assert google.item_type_id == 3


def test_put_madre_no_reinheritance_when_already_resolved(client, cc_catalog, db_session):
    headers = _auth(client)
    _post_staging(client, headers)  # emisor+red resuelven en el POST (institution 1, network 1)
    # recién ahora creamos tarjeta + compra GOOGLE: no debe heredarse en el PUT (ya estaba resuelta)
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
    client.put("/credit-card-statements", json=_madre_body(), headers=headers)
    google = db_session.execute(
        select(StagingCreditCardItem).where(StagingCreditCardItem.description == "GOOGLE *COM PULSO PULS")
    ).scalars().first()
    assert google.item_type_id is None  # no se re-heredó


# ---- PUT ítem ----

def _first_item_id(post_body):
    return post_body["items"][0]["id"]


def test_put_item_200(client, cc_catalog):
    headers = _auth(client)
    body = _post_staging(client, headers)
    item_id = _first_item_id(body)
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(), headers=headers)
    assert r.status_code == 200
    out = r.json()
    assert out["missing_fields"] == []
    assert out["amount"] == "432.10"
    assert out["item_type_id"] == 1


def test_put_item_404_missing(client, cc_catalog):
    import uuid as _uuid
    headers = _auth(client)
    r = client.put(f"/credit-card-statements/items/{_uuid.uuid4()}", json=_item_body(), headers=headers)
    assert r.status_code == 404


def test_put_item_404_other_user(client, cc_catalog):
    headers_a = _auth(client, email="a@b.com")
    body = _post_staging(client, headers_a)
    item_id = _first_item_id(body)
    headers_b = _auth(client, email="b@b.com")
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(), headers=headers_b)
    assert r.status_code == 404


def test_put_item_incomplete(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(amount=None), headers=headers)
    assert r.json()["code"] == "item_incomplete"
    r2 = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(description="   "), headers=headers)
    assert r2.json()["code"] == "item_incomplete"


def test_put_item_currency_not_available(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(currency_id=4), headers=headers)
    assert r.json()["code"] == "currency_not_available"


def test_put_item_amount_invalid(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(amount=0), headers=headers)
    assert r.json()["code"] == "amount_invalid"


def test_put_item_type_invalid(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}", json=_item_body(item_type_id=999), headers=headers)
    assert r.json()["code"] == "item_type_invalid"


def test_put_item_installments_invalid(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}",
                   json=_item_body(current_installment=2, total_installments=None), headers=headers)
    assert r.json()["code"] == "installments_invalid"
    r2 = client.put(f"/credit-card-statements/items/{item_id}",
                    json=_item_body(current_installment=5, total_installments=3), headers=headers)
    assert r2.json()["code"] == "installments_invalid"


def test_put_item_one_payment_ok(client, cc_catalog):
    headers = _auth(client)
    item_id = _first_item_id(_post_staging(client, headers))
    r = client.put(f"/credit-card-statements/items/{item_id}",
                   json=_item_body(current_installment=None, total_installments=None), headers=headers)
    assert r.status_code == 200
    assert r.json()["current_installment"] is None


def test_put_401(client, cc_catalog):
    assert client.put("/credit-card-statements", json=_madre_body()).status_code == 401
    import uuid as _uuid
    assert client.put(f"/credit-card-statements/items/{_uuid.uuid4()}", json=_item_body()).status_code == 401
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statements.py -q
```

- [ ] **Step 3: Agregar al servicio** `app/services/credit_card_statement_service.py`. Imports nuevos:

```python
import uuid

from app.core.errors import AppError, ErrorCode
from app.models.credit_card_item_type import CreditCardItemType
from app.schemas.credit_card_statement import StagingItemUpdate, StagingMadreUpdate
from app.services.scoping import require_user_currency
```

Funciones nuevas (al final del módulo):

```python
def update_staging_madre(db: Session, user: User, payload: StagingMadreUpdate) -> StagingCreditCard:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id).with_for_update()
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)

    required = (
        payload.institution_id, payload.card_network_id, payload.closing_date, payload.due_date,
        payload.current_limit, payload.total_local, payload.total_usd,
        payload.minimum_payment_local, payload.minimum_payment_usd, payload.rates_add_vat,
    )
    if any(v is None for v in required):
        raise AppError(ErrorCode.statement_incomplete)

    inst = db.get(Institution, payload.institution_id)
    if inst is None or inst.country_code != user.country_code:
        raise AppError(ErrorCode.institution_invalid, field="institution_id")
    net = db.get(CreditCardNetwork, payload.card_network_id)
    if net is None or net.country_code != user.country_code:
        raise AppError(ErrorCode.card_network_invalid, field="card_network_id")

    if payload.current_limit <= 0:
        raise AppError(ErrorCode.amount_invalid, field="current_limit")
    for f in ("total_local", "total_usd", "minimum_payment_local", "minimum_payment_usd"):
        if getattr(payload, f) < 0:
            raise AppError(ErrorCode.amount_invalid, field=f)

    prev_institution_id = madre.institution_id
    prev_card_network_id = madre.card_network_id

    madre.institution_id = payload.institution_id
    madre.card_network_id = payload.card_network_id
    madre.closing_date = payload.closing_date
    madre.due_date = payload.due_date
    madre.current_limit = payload.current_limit
    madre.total_local = payload.total_local
    madre.total_usd = payload.total_usd
    madre.minimum_payment_local = payload.minimum_payment_local
    madre.minimum_payment_usd = payload.minimum_payment_usd
    madre.financing_rate_local = payload.financing_rate_local
    madre.overdue_rate_local = payload.overdue_rate_local
    madre.financing_rate_usd = payload.financing_rate_usd
    madre.overdue_rate_usd = payload.overdue_rate_usd
    madre.rates_add_vat = payload.rates_add_vat
    db.flush()

    # herencia solo si recién ahora se resolvió la tarjeta (alguno estaba NULL antes; ambos no-NULL ahora)
    if prev_institution_id is None or prev_card_network_id is None:
        inherited = _inherited_types(db, user.id, payload.institution_id, payload.card_network_id)
        if inherited:
            null_items = db.execute(
                select(StagingCreditCardItem).where(
                    StagingCreditCardItem.staging_credit_card_id == madre.id,
                    StagingCreditCardItem.item_type_id.is_(None),
                )
            ).scalars().all()
            for it in null_items:
                if it.description in inherited:
                    it.item_type_id = inherited[it.description]
            db.flush()

    review_staging_credit_card(db, madre.id)
    db.commit()
    db.refresh(madre)
    return madre


def update_staging_item(
    db: Session, user: User, item_id: uuid.UUID, payload: StagingItemUpdate
) -> StagingCreditCardItem:
    item = db.execute(
        select(StagingCreditCardItem)
        .join(StagingCreditCard, StagingCreditCard.id == StagingCreditCardItem.staging_credit_card_id)
        .where(StagingCreditCardItem.id == item_id, StagingCreditCard.user_id == user.id)
        .with_for_update(of=StagingCreditCardItem)
    ).scalar_one_or_none()
    if item is None:
        raise AppError(ErrorCode.not_found)

    if (
        payload.charge_date is None
        or payload.description is None
        or payload.description.strip() == ""
        or payload.amount is None
        or payload.currency_id is None
        or payload.item_type_id is None
    ):
        raise AppError(ErrorCode.item_incomplete)

    currency = require_user_currency(db, user, payload.currency_id)  # 422 currency_not_available si país/inexistente
    if not currency.allowed_in_credit_card:
        raise AppError(ErrorCode.currency_not_available, field="currency_id")

    if payload.amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")

    if db.get(CreditCardItemType, payload.item_type_id) is None:
        raise AppError(ErrorCode.item_type_invalid, field="item_type_id")

    ci, ti = payload.current_installment, payload.total_installments
    if not (ci is None and ti is None):
        if ci is None or ti is None or ci < 1 or ti < 1 or ci > ti:
            raise AppError(ErrorCode.installments_invalid)

    item.charge_date = payload.charge_date
    item.description = payload.description
    item.amount = payload.amount
    item.currency_id = payload.currency_id
    item.item_type_id = payload.item_type_id
    item.current_installment = ci
    item.total_installments = ti
    db.commit()
    db.refresh(item)
    return item
```

- [ ] **Step 4: Agregar los endpoints al router** `app/routers/credit_card_statements.py`. Imports nuevos:

```python
import uuid

from app.schemas.credit_card_statement import (
    StagingItemUpdate,
    StagingMadreOut,
    StagingMadreUpdate,
    StagingStatementItemOut,
)
```

(Junto a los imports existentes; mantené también `StagingStatementCreate`, `StagingStatementOut`.)

Endpoints (después del POST):

```python
@router.put("/credit-card-statements", response_model=StagingMadreOut)
def update_staging_madre(
    payload: StagingMadreUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StagingMadreOut:
    return StagingMadreOut.from_model(credit_card_statement_service.update_staging_madre(db, user, payload))


@router.put("/credit-card-statements/items/{item_id}", response_model=StagingStatementItemOut)
def update_staging_item(
    item_id: uuid.UUID,
    payload: StagingItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StagingStatementItemOut:
    return StagingStatementItemOut.from_model(
        credit_card_statement_service.update_staging_item(db, user, item_id, payload)
    )
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statements.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/schemas/credit_card_statement.py app/services/credit_card_statement_service.py app/routers/credit_card_statements.py tests/test_credit_card_statements.py && git commit -m "feat: PUT /credit-card-statements (madre + ítem)"
```

---

## Task 4: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (351 previos + los nuevos de los PUT).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/put-credit-card-statements` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** PUT madre (200, 404, statement_incomplete, institution_invalid, card_network_invalid,
  amount_invalid, tasas NULL OK, herencia al resolver, no-reherencia si ya resuelta); PUT ítem (200, 404 ×2,
  item_incomplete, currency_not_available, amount_invalid, item_type_invalid, installments_invalid, pago único,
  401). ✓
- **Sin placeholders:** codes, refactor de schemas, schemas de update, servicio, router y tests completos. ✓
- **DRY/consistencia:** `StagingMadreOut` extraído y `StagingStatementOut` lo extiende (POST sin cambios de
  contrato); `_inherited_types` reusado; `require_user_currency` para país + chequeo `allowed_in_credit_card`;
  herencia solo asigna a ítems con `item_type_id` NULL (no pisa el manual). ✓
- **Validación en el servicio, schema opcional:** garantiza los codes `statement_incomplete`/`item_incomplete`
  en vez de 422 genéricos de Pydantic. ✓

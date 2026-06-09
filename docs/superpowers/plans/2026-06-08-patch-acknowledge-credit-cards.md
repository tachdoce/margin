# PATCH + acknowledge /credit-cards/{id} — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar `PATCH /credit-cards/{id}` (edición parcial → reviewer → motor) y
`POST /credit-cards/{id}/acknowledge` (limpia findings, `is_ready=true` → motor), con el `updated_at`
condicional en el acknowledge.

**Architecture:** Crecen el router/servicio de `credit-cards` (de la #1). Reusa `CreditCardOut`. Schema
`CreditCardUpdate`. 3 error codes nuevos. Reviewer (`review_credit_card`) + motor (`materialize_credit_card`).

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-patch-acknowledge-credit-cards-design.md`

**Branch:** `feat/credit-cards-patch-ack` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-cards-patch-ack
```

---

## Task 1: Error codes + schema

**Files:**
- Modify: `app/core/errors.py`
- Modify: `app/schemas/credit_card.py`

- [ ] **Step 1: Agregar 3 codes** después de `statement_period_not_after_last = (...)`:

```python
    closing_day_invalid = (422, "El día de cierre debe estar entre 1 y 31.")
    card_already_exists = (409, "Ya tenés una tarjeta con ese emisor y esa red.")
    card_has_no_findings = (409, "La tarjeta no tiene observaciones para reconocer.")
```

- [ ] **Step 2: Agregar `CreditCardUpdate`** a `app/schemas/credit_card.py` (no necesita `from_model`):

```python
class CreditCardUpdate(BaseModel):
    institution_id: int | None = None
    card_network_id: int | None = None
    closing_day: int | None = None
```

---

## Task 2: Servicio + router + tests (TDD)

**Files:**
- Modify: `app/services/credit_card_service.py`
- Modify: `app/routers/credit_cards.py`
- Test: `tests/test_credit_cards_mutations.py` (nuevo)

- [ ] **Step 1: Escribir los tests (rojo)**

```python
# tests/test_credit_cards_mutations.py
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.credit_card import CreditCard
from app.models.credit_card_network import CreditCardNetwork
from app.models.currency import Currency
from app.models.institution import Institution

from tests.test_credit_cards_read import _auth, _last_user, _make_card, _make_statement

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 2, 1, tzinfo=timezone.utc)


@pytest.fixture
def cc_full(db_session, seed_cc_refs):
    """seed_cc_refs (Peso 1, institución 1, red 1, tipo 1) + USD (Dólar 3) que el motor necesita."""
    db_session.add(
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
    )
    db_session.flush()


# ---- PATCH ----

def test_patch_closing_day_ok(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)  # existente (created_at != updated_at)
    r = client.patch(f"/credit-cards/{card.id}", json={"closing_day": 15}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["closing_day"] == 15
    assert body["review_findings"] == []  # sin statement -> rama existente sin closing_day_changed
    assert body["is_ready"] is True


def test_patch_404_other_user(client, db_session, cc_full):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a, created_at=T1)
    headers_b = _auth(client, email="b@b.com")
    assert client.patch(f"/credit-cards/{card.id}", json={"closing_day": 15}, headers=headers_b).status_code == 404


def test_patch_404_soft_deleted(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, deleted_at=datetime.now(timezone.utc))
    assert client.patch(f"/credit-cards/{card.id}", json={"closing_day": 15}, headers=headers).status_code == 404


def test_patch_empty(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "empty_patch"


def test_patch_institution_invalid(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={"institution_id": 999}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "institution_invalid"


def test_patch_card_network_invalid(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    r = client.patch(f"/credit-cards/{card.id}", json={"card_network_id": 999}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "card_network_invalid"


def test_patch_closing_day_invalid(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)
    assert client.patch(f"/credit-cards/{card.id}", json={"closing_day": 0}, headers=headers).json()["code"] == "closing_day_invalid"
    assert client.patch(f"/credit-cards/{card.id}", json={"closing_day": 32}, headers=headers).json()["code"] == "closing_day_invalid"


def test_patch_card_already_exists(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    # otra institución/red para mover la combinación
    db_session.add_all([
        Institution(id=2, country_code="UY", name="BROU", visible=True),
        CreditCardNetwork(id=2, country_code="UY", code="visa", name="Visa"),
    ])
    db_session.flush()
    _make_card(db_session, user, created_at=T1)  # institución 1 + red 1 (vigente)
    other = _make_card(db_session, user, created_at=T1, institution_id=2, card_network_id=2)
    # mover `other` a (1,1) choca con la primera
    r = client.patch(f"/credit-cards/{other.id}", json={"institution_id": 1, "card_network_id": 1}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "card_already_exists"


def test_patch_closing_day_changed(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, closing_day=13)
    _make_statement(db_session, card, issue_year=2026, issue_month=4, closing_day=13)
    r = client.patch(f"/credit-cards/{card.id}", json={"closing_day": 25}, headers=headers)  # dif 12
    assert r.json()["review_findings"] == ["closing_day_changed"]
    assert r.json()["is_ready"] is False


def test_patch_401(client, cc_full):
    import uuid
    assert client.patch(f"/credit-cards/{uuid.uuid4()}", json={"closing_day": 15}).status_code == 401


# ---- acknowledge ----

def test_ack_new_card_graduates(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    # nueva: created_at == updated_at (server default, misma tx) + finding
    card = _make_card(db_session, user, review_findings='["closing_day_inferred"]', is_ready=False)
    assert card.created_at == card.updated_at
    r = client.post(f"/credit-cards/{card.id}/acknowledge", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["review_findings"] == [] and r.json()["is_ready"] is True
    db_session.refresh(card)
    assert card.updated_at != card.created_at  # se graduó de "nueva"


def test_ack_existing_preserves_updated_at(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, updated_at=T2,
                      review_findings='["closing_day_changed"]', is_ready=False)
    client.post(f"/credit-cards/{card.id}/acknowledge", json={}, headers=headers)
    db_session.refresh(card)
    assert card.updated_at == T2  # se preservó


def test_ack_404_soft_deleted(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, deleted_at=datetime.now(timezone.utc),
                      review_findings='["closing_day_inferred"]', is_ready=False)
    assert client.post(f"/credit-cards/{card.id}/acknowledge", json={}, headers=headers).status_code == 404


def test_ack_409_no_findings(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)  # review_findings '[]' por defecto
    r = client.post(f"/credit-cards/{card.id}/acknowledge", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "card_has_no_findings"


def test_ack_401(client, cc_full):
    import uuid
    assert client.post(f"/credit-cards/{uuid.uuid4()}/acknowledge", json={}).status_code == 401
```

> `_make_card` (de `test_credit_cards_read`) hace `CreditCard(**{**_card_kwargs(user), **over})`, así que
> `created_at`/`updated_at`/`review_findings`/`is_ready`/`deleted_at` se pueden pasar como override.
> `_card_kwargs` trae `is_ready=False` y `review_findings="[]"`.

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_mutations.py -q
```

- [ ] **Step 3: Agregar al servicio** `app/services/credit_card_service.py`. Imports nuevos:

```python
from datetime import datetime, timezone

from sqlalchemy import select, update  # 'update' es nuevo

from app.models.credit_card_network import CreditCardNetwork
from app.models.institution import Institution
from app.schemas.credit_card import CreditCardUpdate
from app.services.cash_flow.credit_cards import materialize_credit_card
from app.services.review.credit_cards import review_credit_card
```

(`select` ya estaba; sumar `update`. `AppError`/`ErrorCode`/`CreditCard`/`User` ya están.)

Funciones nuevas (al final del módulo):

```python
def update_credit_card(
    db: Session, user: User, card_id: uuid.UUID, payload: CreditCardUpdate
) -> CreditCard:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id,
            CreditCard.user_id == user.id,
            CreditCard.deleted_at.is_(None),
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)

    if payload.institution_id is None and payload.card_network_id is None and payload.closing_day is None:
        raise AppError(ErrorCode.empty_patch)

    if payload.institution_id is not None:
        inst = db.get(Institution, payload.institution_id)
        if inst is None or inst.country_code != user.country_code:
            raise AppError(ErrorCode.institution_invalid, field="institution_id")
    if payload.card_network_id is not None:
        net = db.get(CreditCardNetwork, payload.card_network_id)
        if net is None or net.country_code != user.country_code:
            raise AppError(ErrorCode.card_network_invalid, field="card_network_id")
    if payload.closing_day is not None and not (1 <= payload.closing_day <= 31):
        raise AppError(ErrorCode.closing_day_invalid, field="closing_day")

    # unicidad: combinación final contra otra vigente del usuario
    new_inst = payload.institution_id if payload.institution_id is not None else card.institution_id
    new_net = payload.card_network_id if payload.card_network_id is not None else card.card_network_id
    if new_inst != card.institution_id or new_net != card.card_network_id:
        clash = db.execute(
            select(CreditCard.id).where(
                CreditCard.user_id == user.id,
                CreditCard.institution_id == new_inst,
                CreditCard.card_network_id == new_net,
                CreditCard.deleted_at.is_(None),
                CreditCard.id != card.id,
            )
        ).first()
        if clash is not None:
            raise AppError(ErrorCode.card_already_exists)

    if payload.institution_id is not None:
        card.institution_id = payload.institution_id
    if payload.card_network_id is not None:
        card.card_network_id = payload.card_network_id
    if payload.closing_day is not None:
        card.closing_day = payload.closing_day
    db.flush()

    review_credit_card(db, card.id)
    materialize_credit_card(db, card.id)
    db.commit()
    db.refresh(card)
    return card


def acknowledge_credit_card(db: Session, user: User, card_id: uuid.UUID) -> CreditCard:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id,
            CreditCard.user_id == user.id,
            CreditCard.deleted_at.is_(None),
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)
    if card.review_findings == "[]":
        raise AppError(ErrorCode.card_has_no_findings)

    # updated_at: bump si era nueva (created_at == updated_at) para que deje de serlo; si no, preservar.
    new_updated_at = (
        datetime.now(timezone.utc) if card.created_at == card.updated_at else card.updated_at
    )
    db.execute(
        update(CreditCard)
        .where(CreditCard.id == card.id)
        .values(
            review_findings="[]",
            user_acknowledged_at=datetime.now(timezone.utc),
            is_ready=True,
            updated_at=new_updated_at,
        )
    )
    materialize_credit_card(db, card.id)
    db.commit()
    db.refresh(card)
    return card
```

- [ ] **Step 4: Agregar los endpoints al router** `app/routers/credit_cards.py`. Sumar `CreditCardUpdate` al
  import de schemas y los dos endpoints:

```python
from app.schemas.credit_card import CreditCardOut, CreditCardUpdate, StatementItemOut, StatementOut


@router.patch("/credit-cards/{card_id}", response_model=CreditCardOut)
def update_credit_card(
    card_id: uuid.UUID,
    payload: CreditCardUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    return CreditCardOut.from_model(credit_card_service.update_credit_card(db, user, card_id, payload))


@router.post("/credit-cards/{card_id}/acknowledge", response_model=CreditCardOut)
def acknowledge_credit_card(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    return CreditCardOut.from_model(credit_card_service.acknowledge_credit_card(db, user, card_id))
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_mutations.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/schemas/credit_card.py app/services/credit_card_service.py app/routers/credit_cards.py tests/test_credit_cards_mutations.py && git commit -m "feat: PATCH + acknowledge /credit-cards/{id}"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (409 previos + los nuevos).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/credit-cards-patch-ack` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** PATCH (closing_day ok, 404 ×2 [otro usuario/soft-deleted], empty_patch,
  institution_invalid, card_network_invalid, closing_day_invalid, card_already_exists, closing_day_changed,
  401); acknowledge (nueva se gradúa, existente preserva updated_at, 404 soft-deleted, 409 no-findings, 401). ✓
- **Sin placeholders:** codes, schema, servicio (PATCH + ack), router y tests completos. ✓
- **Sutilezas de test cubiertas:** tarjetas "existentes" con `created_at=T1` explícito (si no, `now()` fijo por
  transacción daría `created_at==updated_at` y el reviewer las trataría como nuevas); fixture `cc_full` siembra
  Dólar(3) que el motor necesita al materializar. ✓
- **Consistencia:** acknowledge con `updated_at` condicional (bump si nueva, preserva si existente) vía Core
  `update`; ambos disparan el motor; PATCH reabre el ciclo vía reviewer; unicidad excluye la propia tarjeta y
  filtra vigentes; reusa `CreditCardOut`. ✓

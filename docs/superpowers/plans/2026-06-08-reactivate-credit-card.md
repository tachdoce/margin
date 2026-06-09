# POST /credit-cards/{id}/reactivate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar `POST /credit-cards/{id}/reactivate`: limpia `deleted_at` de una tarjeta soft-deleted,
recalcula el ciclo (reviewer) y reconstruye las proyecciones (motor). 200.

**Architecture:** Crece el servicio/router de `credit-cards`. Un error code nuevo. Reusa `review_credit_card`,
`materialize_credit_card`, `CreditCardOut`.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-reactivate-credit-card-design.md`

**Branch:** `feat/credit-cards-reactivate` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-cards-reactivate
```

---

## Task 1: Error code

**Files:**
- Modify: `app/core/errors.py`

- [ ] **Step 1: Agregar** después de `statement_has_payments = (...)`:

```python
    card_not_deleted = (409, "La tarjeta no está borrada.")
```

---

## Task 2: Servicio + router + tests (TDD)

**Files:**
- Modify: `app/services/credit_card_service.py`
- Modify: `app/routers/credit_cards.py`
- Test: `tests/test_credit_cards_reactivate.py` (nuevo)

- [ ] **Step 1: Escribir los tests (rojo)**

```python
# tests/test_credit_cards_reactivate.py
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.credit_card import CreditCard
from app.models.currency import Currency

from tests.test_credit_cards_read import _auth, _last_user, _make_card, _make_statement

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def cc_full(db_session, seed_cc_refs):
    """seed_cc_refs + USD (Dólar 3) que el motor necesita al materializar."""
    db_session.add(
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
    )
    db_session.flush()


def _card_db(db_session, card_id):
    return db_session.execute(select(CreditCard).where(CreditCard.id == card_id)).scalar_one_or_none()


def _cc_entries(db_session, card_id):
    return db_session.execute(
        select(CashFlowEntry).where(
            CashFlowEntry.source_type == "tarjeta_credito", CashFlowEntry.source_id == card_id
        )
    ).scalars().all()


def test_reactivate_200(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, is_ready=True,
                      deleted_at=datetime.now(timezone.utc), closing_day=13)
    _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=13)
    card_id = card.id
    r = client.post(f"/credit-cards/{card_id}/reactivate", json={}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["is_deleted"] is False
    assert body["review_findings"] == []
    assert body["is_ready"] is True
    assert _card_db(db_session, card_id).deleted_at is None


def test_reactivate_materializes(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, is_ready=True,
                      deleted_at=datetime.now(timezone.utc), closing_day=13)
    _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=13)  # total_local 100 > 0
    card_id = card.id
    client.post(f"/credit-cards/{card_id}/reactivate", json={}, headers=headers)
    assert len(_cc_entries(db_session, card_id)) >= 1  # el motor reproyectó


def test_reactivate_404_nonexistent(client, cc_full):
    headers = _auth(client)
    assert client.post(f"/credit-cards/{uuid.uuid4()}/reactivate", json={}, headers=headers).status_code == 404


def test_reactivate_404_other_user(client, db_session, cc_full):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a, created_at=T1, deleted_at=datetime.now(timezone.utc))
    headers_b = _auth(client, email="b@b.com")
    assert client.post(f"/credit-cards/{card.id}/reactivate", json={}, headers=headers_b).status_code == 404


def test_reactivate_409_not_deleted(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1)  # vigente (deleted_at None)
    r = client.post(f"/credit-cards/{card.id}/reactivate", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "card_not_deleted"


def test_reactivate_409_already_exists(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    _make_card(db_session, user, created_at=T1)  # vigente (1,1)
    soft = _make_card(db_session, user, created_at=T1, institution_id=1, card_network_id=1,
                      deleted_at=datetime.now(timezone.utc))  # soft-deleted (1,1)
    soft_id = soft.id
    r = client.post(f"/credit-cards/{soft_id}/reactivate", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "card_already_exists"
    assert _card_db(db_session, soft_id).deleted_at is not None  # sigue soft-deleted


def test_reactivate_closing_day_changed(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, created_at=T1, is_ready=True,
                      deleted_at=datetime.now(timezone.utc), closing_day=13)
    _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=25)  # dif 12
    card_id = card.id
    r = client.post(f"/credit-cards/{card_id}/reactivate", json={}, headers=headers)
    assert r.json()["review_findings"] == ["closing_day_changed"]
    assert r.json()["is_ready"] is False
    assert _cc_entries(db_session, card_id) == []  # is_ready false -> motor no-op


def test_reactivate_401(client, cc_full):
    assert client.post(f"/credit-cards/{uuid.uuid4()}/reactivate", json={}).status_code == 401
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_reactivate.py -q
```

- [ ] **Step 3: Agregar al servicio** `app/services/credit_card_service.py` (sin imports nuevos: `select`,
  `CreditCard`, `review_credit_card`, `materialize_credit_card`, `AppError`/`ErrorCode`, `User` ya están).
  Función nueva (al final del módulo):

```python
def reactivate_credit_card(db: Session, user: User, card_id: uuid.UUID) -> CreditCard:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id, CreditCard.user_id == user.id
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)
    if card.deleted_at is None:
        raise AppError(ErrorCode.card_not_deleted)

    clash = db.execute(
        select(CreditCard.id).where(
            CreditCard.user_id == user.id,
            CreditCard.institution_id == card.institution_id,
            CreditCard.card_network_id == card.card_network_id,
            CreditCard.deleted_at.is_(None),
            CreditCard.id != card.id,
        )
    ).first()
    if clash is not None:
        raise AppError(ErrorCode.card_already_exists)

    card.deleted_at = None
    db.flush()
    review_credit_card(db, card.id)
    materialize_credit_card(db, card.id)
    db.commit()
    db.refresh(card)
    return card
```

- [ ] **Step 4: Agregar el endpoint al router** `app/routers/credit_cards.py`:

```python
@router.post("/credit-cards/{card_id}/reactivate", response_model=CreditCardOut)
def reactivate_credit_card(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    return CreditCardOut.from_model(credit_card_service.reactivate_credit_card(db, user, card_id))
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_reactivate.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/services/credit_card_service.py app/routers/credit_cards.py tests/test_credit_cards_reactivate.py && git commit -m "feat: POST /credit-cards/{id}/reactivate"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (436 previos + los nuevos).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/credit-cards-reactivate` a `main` (1 commit). Push **manual**. Post-cierre (lo hace
  el coordinador): crear la página de Notion del endpoint.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** 200 (reactiva, is_deleted false, vigente), materializa (motor reproyecta), 404
  (inexistente / otro usuario), 409 `card_not_deleted` (vigente), 409 `card_already_exists` (conflicto de
  combinación; sigue soft-deleted), `closing_day_changed` al reactivar (is_ready false, motor no-op), 401. ✓
- **Sin placeholders:** code, servicio, router y tests completos. ✓
- **Consistencia:** pipeline reviewer → motor; `deleted_at=None` (onupdate bumpea updated_at → existente, no
  nueva); conflicto excluye la propia y filtra vigentes; fixture `cc_full` con Dólar; `created_at=T1` explícito
  en las soft-deleted; `user_id` del token. Tests ejercitan la rama con findings (reviewers crecen). ✓

# DELETE /credit-cards/{id}/statements (deshacer última promoción) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar `DELETE /credit-cards/{id}/statements`: borra el último resumen de la tarjeta (con sus
items), rechaza si tiene pagos reales (409), y reproyecta vía el motor. 204.

**Architecture:** Crece el servicio/router de `credit-cards`. Un error code nuevo. Reusa
`materialize_credit_card`.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-delete-last-statement-design.md`

**Branch:** `feat/credit-cards-delete-statement` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-cards-delete-statement
```

---

## Task 1: Error code

**Files:**
- Modify: `app/core/errors.py`

- [ ] **Step 1: Agregar** después de `card_has_no_findings = (...)`:

```python
    statement_has_payments = (409, "No se puede borrar un resumen que ya tiene pagos registrados.")
```

---

## Task 2: Servicio + router + tests (TDD)

**Files:**
- Modify: `app/services/credit_card_service.py`
- Modify: `app/routers/credit_cards.py`
- Test: `tests/test_credit_cards_delete_statement.py` (nuevo)

- [ ] **Step 1: Escribir los tests (rojo)**

```python
# tests/test_credit_cards_delete_statement.py
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.models.currency import Currency

from tests.test_credit_cards_read import _auth, _last_user, _make_card, _make_statement
from tests.test_credit_cards_delete import _make_entry, _make_payment


@pytest.fixture
def cc_full(db_session, seed_cc_refs):
    """seed_cc_refs + USD (Dólar 3) que el motor necesita al materializar."""
    db_session.add(
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
    )
    db_session.flush()


def _make_item(db_session, statement):
    it = CreditCardStatementItem(
        credit_card_statement_id=statement.id, charge_date=date(2026, 5, 2),
        description="X", amount=Decimal("10.00"), currency_id=1,
        current_installment=None, total_installments=None, item_type_id=1,
    )
    db_session.add(it)
    db_session.flush()
    return it


def test_delete_last_204(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, is_ready=True)
    apr = _make_statement(db_session, card, issue_year=2026, issue_month=4, closing_day=13)
    may = _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=13)
    item = _make_item(db_session, may)
    card_id, may_id, apr_id, item_id = card.id, may.id, apr.id, item.id  # capturar antes del delete
    r = client.delete(f"/credit-cards/{card_id}/statements", headers=headers)
    assert r.status_code == 204
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.id == may_id)).scalar_one_or_none() is None
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.id == apr_id)).scalar_one_or_none() is not None  # el anterior queda
    assert db_session.execute(select(CreditCardStatementItem).where(CreditCardStatementItem.id == item_id)).scalar_one_or_none() is None  # items por cascade


def test_delete_last_404_no_statements(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, is_ready=True)
    assert client.delete(f"/credit-cards/{card.id}/statements", headers=headers).status_code == 404


def test_delete_last_404_nonexistent(client, cc_full):
    headers = _auth(client)
    assert client.delete(f"/credit-cards/{uuid.uuid4()}/statements", headers=headers).status_code == 404


def test_delete_last_404_other_user(client, db_session, cc_full):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a, is_ready=True)
    _make_statement(db_session, card)
    headers_b = _auth(client, email="b@b.com")
    assert client.delete(f"/credit-cards/{card.id}/statements", headers=headers_b).status_code == 404


def test_delete_last_409_has_payments(client, db_session, cc_full):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, is_ready=True)
    may = _make_statement(db_session, card, issue_year=2026, issue_month=5)
    entry = _make_entry(db_session, card, issue_month=5)  # período del último statement
    _make_payment(db_session, entry, plan_id=None)  # pago real
    may_id = may.id
    r = client.delete(f"/credit-cards/{card.id}/statements", headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_has_payments"
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.id == may_id)).scalar_one_or_none() is not None  # no se borró


def test_delete_last_401(client, cc_full):
    assert client.delete(f"/credit-cards/{uuid.uuid4()}/statements").status_code == 401
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_delete_statement.py -q
```

- [ ] **Step 3: Agregar al servicio** `app/services/credit_card_service.py`. No requiere imports nuevos
  (`select`, `func`, `CreditCard`, `CreditCardStatement`, `CashFlowEntry`, `CashFlowPayment`,
  `materialize_credit_card`, `AppError`/`ErrorCode`, `User` ya están). Función nueva (al final del módulo):

```python
def delete_last_statement(db: Session, user: User, card_id: uuid.UUID) -> None:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id, CreditCard.user_id == user.id
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)

    statement = db.execute(
        select(CreditCardStatement)
        .where(CreditCardStatement.credit_card_id == card.id)
        .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
        .limit(1)
    ).scalar_one_or_none()
    if statement is None:
        raise AppError(ErrorCode.not_found)

    real_payments = db.execute(
        select(func.count())
        .select_from(CashFlowPayment)
        .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
        .where(
            CashFlowEntry.source_type == "tarjeta_credito",
            CashFlowEntry.source_id == card.id,
            CashFlowEntry.issue_year == statement.issue_year,
            CashFlowEntry.issue_month == statement.issue_month,
            CashFlowPayment.plan_id.is_(None),
        )
    ).scalar_one()
    if real_payments > 0:
        raise AppError(ErrorCode.statement_has_payments)

    db.delete(statement)  # items por ON DELETE CASCADE; purchases NO se tocan
    db.flush()
    materialize_credit_card(db, card.id)  # reproyecta desde el nuevo último
    db.commit()
```

- [ ] **Step 4: Agregar el endpoint al router** `app/routers/credit_cards.py` (después del DELETE de tarjeta):

```python
@router.delete("/credit-cards/{card_id}/statements", status_code=status.HTTP_204_NO_CONTENT)
def delete_last_statement(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    credit_card_service.delete_last_statement(db, user, card_id)
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_delete_statement.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/services/credit_card_service.py app/routers/credit_cards.py tests/test_credit_cards_delete_statement.py && git commit -m "feat: DELETE /credit-cards/{id}/statements (deshacer última promoción)"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (430 previos + los nuevos).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/credit-cards-delete-statement` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** 204 (borra último + items por cascade, el anterior queda, motor corre), 404 (sin
  resúmenes / inexistente / otro usuario), 409 `statement_has_payments` (no se borra), 401. ✓
- **Sin placeholders:** code, servicio, router y tests completos. ✓
- **Consistencia:** resuelve el último por `(issue_year, issue_month)`; chequeo de pagos reales del período
  antes de tocar nada; `db.delete(statement)` (items cascade), purchases intactos; motor reproyecta; ids
  capturados antes del delete (sesión compartida + commit expira objetos); fixture `cc_full` con Dólar para el
  motor; `user_id` del token. ✓

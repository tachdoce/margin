# DELETE /credit-cards/{id} (borrado híbrido) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar `DELETE /credit-cards/{id}` con decisión hard-delete (sin pagos reales) / soft-delete
(con pagos reales), borrado orquestado y 204.

**Architecture:** Crece el servicio/router de `credit-cards`. Sin schemas ni error codes nuevos.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-delete-credit-cards-design.md`

**Branch:** `feat/credit-cards-delete` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-cards-delete
```

---

## Task 1: Servicio + router + tests (TDD)

**Files:**
- Modify: `app/services/credit_card_service.py`
- Modify: `app/routers/credit_cards.py`
- Test: `tests/test_credit_cards_delete.py` (nuevo)

- [ ] **Step 1: Escribir los tests (rojo)**

```python
# tests/test_credit_cards_delete.py
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.credit_card import CreditCard
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem

from tests.test_credit_cards_read import _auth, _last_user, _make_card, _make_statement


def _make_item(db_session, statement, **over):
    it = CreditCardStatementItem(
        credit_card_statement_id=statement.id, charge_date=date(2026, 2, 2),
        description="X", amount=Decimal("100.00"), currency_id=1,
        current_installment=None, total_installments=None, item_type_id=1,
    )
    for k, v in over.items():
        setattr(it, k, v)
    db_session.add(it)
    db_session.flush()
    return it


def _make_purchase(db_session, card):
    p = CreditCardPurchase(
        credit_card_id=card.id, description="X", charge_date=date(2026, 2, 2),
        amount=Decimal("100.00"), currency_id=1, total_installments=None, item_type_id=1,
        last_statement_closing_date=date(2026, 5, 13),
    )
    db_session.add(p)
    db_session.flush()
    return p


def _make_entry(db_session, card, **over):
    e = CashFlowEntry(
        user_id=card.user_id, event_date=date(2026, 5, 25), is_income=False,
        amount=Decimal("100.00"), currency_id=1, issue_year=2026, issue_month=5,
        source_type="tarjeta_credito", source_id=card.id,
    )
    for k, v in over.items():
        setattr(e, k, v)
    db_session.add(e)
    db_session.flush()
    return e


def _make_payment(db_session, entry, plan_id=None):
    p = CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("10.00"), plan_id=plan_id)
    db_session.add(p)
    db_session.flush()
    return p


def _card_exists(db_session, card_id):
    return db_session.execute(select(CreditCard).where(CreditCard.id == card_id)).scalar_one_or_none()


def test_hard_delete(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    st = _make_statement(db_session, card)
    _make_item(db_session, st)
    _make_purchase(db_session, card)
    _make_entry(db_session, card)  # sin pagos -> count real 0 -> hard
    r = client.delete(f"/credit-cards/{card.id}", headers=headers)
    assert r.status_code == 204
    assert _card_exists(db_session, card.id) is None
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.credit_card_id == card.id)).scalars().all() == []
    assert db_session.execute(select(CreditCardStatementItem).where(CreditCardStatementItem.credit_card_statement_id == st.id)).scalars().all() == []
    assert db_session.execute(select(CreditCardPurchase).where(CreditCardPurchase.credit_card_id == card.id)).scalars().all() == []
    assert db_session.execute(select(CashFlowEntry).where(CashFlowEntry.source_type == "tarjeta_credito", CashFlowEntry.source_id == card.id)).scalars().all() == []


def test_soft_delete(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    st = _make_statement(db_session, card)
    _make_purchase(db_session, card)
    entry_paid = _make_entry(db_session, card, issue_month=5)
    _make_payment(db_session, entry_paid, plan_id=None)  # pago real
    entry_unpaid = _make_entry(db_session, card, issue_month=6, event_date=date(2026, 6, 25))  # sin pago
    r = client.delete(f"/credit-cards/{card.id}", headers=headers)
    assert r.status_code == 204
    card_db = _card_exists(db_session, card.id)
    assert card_db is not None and card_db.deleted_at is not None  # soft-deleted
    assert _entry_exists(db_session, entry_paid.id) is not None    # sobrevive
    assert _entry_exists(db_session, entry_unpaid.id) is None      # se borró
    assert db_session.execute(select(CreditCardStatement).where(CreditCardStatement.credit_card_id == card.id)).scalars().all() != []
    assert db_session.execute(select(CreditCardPurchase).where(CreditCardPurchase.credit_card_id == card.id)).scalars().all() != []


def _entry_exists(db_session, entry_id):
    return db_session.execute(select(CashFlowEntry).where(CashFlowEntry.id == entry_id)).scalar_one_or_none()


def test_delete_404_nonexistent(client, seed_cc_refs):
    headers = _auth(client)
    assert client.delete(f"/credit-cards/{uuid.uuid4()}", headers=headers).status_code == 404


def test_delete_404_other_user(client, db_session, seed_cc_refs):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a)
    headers_b = _auth(client, email="b@b.com")
    assert client.delete(f"/credit-cards/{card.id}", headers=headers_b).status_code == 404


def test_delete_404_already_soft_deleted(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, deleted_at=datetime.now(timezone.utc))
    assert client.delete(f"/credit-cards/{card.id}", headers=headers).status_code == 404


def test_delete_401(client, seed_cc_refs):
    assert client.delete(f"/credit-cards/{uuid.uuid4()}").status_code == 401
```

> `_entry_exists` se usa antes de su definición en el archivo; Python lo resuelve en runtime (la función ya
> está definida cuando corre el test). Si preferís, movelo arriba — es indistinto.

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_delete.py -q
```

- [ ] **Step 3: Agregar al servicio** `app/services/credit_card_service.py`. Imports nuevos:

```python
from sqlalchemy import delete, func, select, update  # 'delete' y 'func' son nuevos

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
```

(`datetime`/`timezone`, `CreditCard`, `CreditCardStatement`, `CreditCardPurchase`, `AppError`/`ErrorCode`,
`User` ya están de los sub-proyectos anteriores.)

Función nueva (al final del módulo):

```python
def delete_credit_card(db: Session, user: User, card_id: uuid.UUID) -> None:
    card = db.execute(
        select(CreditCard).where(
            CreditCard.id == card_id,
            CreditCard.user_id == user.id,
            CreditCard.deleted_at.is_(None),
        ).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)

    real_payments = db.execute(
        select(func.count())
        .select_from(CashFlowPayment)
        .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
        .where(
            CashFlowEntry.source_type == "tarjeta_credito",
            CashFlowEntry.source_id == card.id,
            CashFlowPayment.plan_id.is_(None),
        )
    ).scalar_one()

    if real_payments == 0:
        # hard-delete total (orden por las FKs RESTRICT de statements/purchases hacia credit_cards)
        db.execute(
            delete(CashFlowEntry)
            .where(CashFlowEntry.source_type == "tarjeta_credito", CashFlowEntry.source_id == card.id)
            .execution_options(synchronize_session=False)
        )
        db.execute(
            delete(CreditCardPurchase)
            .where(CreditCardPurchase.credit_card_id == card.id)
            .execution_options(synchronize_session=False)
        )
        db.execute(
            delete(CreditCardStatement)
            .where(CreditCardStatement.credit_card_id == card.id)
            .execution_options(synchronize_session=False)
        )
        db.delete(card)
    else:
        # soft-delete: borrar solo las entries sin pago real; la tarjeta y la historia sobreviven
        paid_entry_ids = (
            select(CashFlowPayment.cash_flow_entry_id)
            .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
            .where(
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.source_id == card.id,
                CashFlowPayment.plan_id.is_(None),
            )
        )
        db.execute(
            delete(CashFlowEntry)
            .where(
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.source_id == card.id,
                CashFlowEntry.id.not_in(paid_entry_ids),
            )
            .execution_options(synchronize_session=False)
        )
        card.deleted_at = datetime.now(timezone.utc)

    db.commit()
```

- [ ] **Step 4: Agregar el endpoint al router** `app/routers/credit_cards.py`. Asegurar `status` en el import
  de fastapi (`from fastapi import APIRouter, Depends, status`) y agregar:

```python
@router.delete("/credit-cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credit_card(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    credit_card_service.delete_credit_card(db, user, card_id)
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_delete.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/credit_card_service.py app/routers/credit_cards.py tests/test_credit_cards_delete.py && git commit -m "feat: DELETE /credit-cards/{id} (borrado híbrido soft/hard)"
```

---

## Task 2: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (424 previos + los nuevos).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/credit-cards-delete` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** hard-delete (todo desaparece), soft-delete (tarjeta marcada, entry con pago real
  sobrevive, entry sin pago se borra, statement/purchase quedan), 404 (inexistente / otro usuario / ya
  soft-deleted), 401. ✓
- **Sin placeholders:** servicio, router y tests completos. ✓
- **Consistencia:** orden de borrado por FKs RESTRICT (entries → purchases → statements → card); cascades
  nativas (payments→entries, items→statements); conteo de pagos reales `plan_id IS NULL`; soft-delete borra
  solo entries sin pago real (`id.not_in(subquery)`); `synchronize_session=False` en los bulk delete;
  `user_id` del token + vigente. ✓

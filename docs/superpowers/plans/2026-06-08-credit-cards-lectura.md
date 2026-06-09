# Credit-cards — Lectura (GET ×3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar los tres GET de credit-cards (lista de tarjetas, historial de resúmenes, cargos de un
resumen), solo-lectura, con respuestas envueltas.

**Architecture:** Router `credit_cards.py` → `credit_card_service.py` → modelos. Schemas en
`credit_card.py` (`CreditCardOut`, `StatementOut`, `StatementItemOut`), reusados por #2–#4. Sin escritura.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-credit-cards-lectura-design.md`

**Branch:** `feat/credit-cards-lectura` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-cards-lectura
```

---

## Task 1: Schemas

**Files:**
- Create: `app/schemas/credit_card.py`

- [ ] **Step 1: Escribir los schemas**

```python
import json
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem


class CreditCardOut(BaseModel):
    id: uuid.UUID
    institution_id: int
    card_network_id: int
    current_limit: Decimal
    closing_day: int
    financing_rate_local: Decimal
    overdue_rate_local: Decimal
    financing_rate_usd: Decimal
    overdue_rate_usd: Decimal
    rates_add_vat: bool
    review_findings: list[str]
    is_ready: bool
    is_deleted: bool

    @classmethod
    def from_model(cls, c: CreditCard) -> "CreditCardOut":
        return cls(
            id=c.id,
            institution_id=c.institution_id,
            card_network_id=c.card_network_id,
            current_limit=c.current_limit,
            closing_day=c.closing_day,
            financing_rate_local=c.financing_rate_local,
            overdue_rate_local=c.overdue_rate_local,
            financing_rate_usd=c.financing_rate_usd,
            overdue_rate_usd=c.overdue_rate_usd,
            rates_add_vat=c.rates_add_vat,
            review_findings=json.loads(c.review_findings),
            is_ready=c.is_ready,
            is_deleted=c.deleted_at is not None,
        )


class StatementOut(BaseModel):
    id: uuid.UUID
    issue_year: int
    issue_month: int
    closing_date: date
    due_date: date
    total_local: Decimal
    total_usd: Decimal
    minimum_payment_local: Decimal
    minimum_payment_usd: Decimal

    @classmethod
    def from_model(cls, s: CreditCardStatement) -> "StatementOut":
        return cls(
            id=s.id,
            issue_year=s.issue_year,
            issue_month=s.issue_month,
            closing_date=s.closing_date,
            due_date=s.due_date,
            total_local=s.total_local,
            total_usd=s.total_usd,
            minimum_payment_local=s.minimum_payment_local,
            minimum_payment_usd=s.minimum_payment_usd,
        )


class StatementItemOut(BaseModel):
    id: uuid.UUID
    charge_date: date
    description: str
    amount: Decimal
    currency_id: int
    current_installment: int | None
    total_installments: int | None
    item_type_id: int

    @classmethod
    def from_model(cls, it: CreditCardStatementItem) -> "StatementItemOut":
        return cls(
            id=it.id,
            charge_date=it.charge_date,
            description=it.description,
            amount=it.amount,
            currency_id=it.currency_id,
            current_installment=it.current_installment,
            total_installments=it.total_installments,
            item_type_id=it.item_type_id,
        )
```

---

## Task 2: Servicio + router + tests (TDD)

**Files:**
- Create: `app/services/credit_card_service.py`
- Create: `app/routers/credit_cards.py`
- Modify: `app/main.py`
- Test: `tests/test_credit_cards_read.py`

- [ ] **Step 1: Escribir los tests (rojo)**

```python
# tests/test_credit_cards_read.py
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.models.user import User

from tests.test_credit_cards_model import _card_kwargs


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    return db_session.execute(select(User)).scalars().all()[-1]  # el último registrado


def _make_card(db_session, user, **over):
    card = CreditCard(**{**_card_kwargs(user), **over})
    db_session.add(card)
    db_session.flush()
    return card


def _make_statement(db_session, card, *, issue_year=2026, issue_month=5, closing_day=13):
    s = CreditCardStatement(
        credit_card_id=card.id, issue_year=issue_year, issue_month=issue_month,
        closing_date=date(issue_year, issue_month, closing_day),
        due_date=date(issue_year, issue_month, 25),
        total_local=Decimal("100.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("10.00"), minimum_payment_usd=Decimal("0.00"),
    )
    db_session.add(s)
    db_session.flush()
    return s


# ---- GET /credit-cards ----

def test_list_empty(client, seed_cc_refs):
    headers = _auth(client)
    r = client.get("/credit-cards", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"credit_cards": []}


def test_list_vigente_y_soft_deleted(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    _make_card(db_session, user)  # vigente
    _make_card(db_session, user, institution_id=1, card_network_id=1, deleted_at=datetime.now(timezone.utc))
    # nota: dos del mismo emisor+red chocan con el índice parcial solo si ambas vigentes;
    # una soft-deleted no choca. Para evitar el índice, la segunda va soft-deleted (deleted_at con valor).
    r = client.get("/credit-cards", headers=headers)
    cards = r.json()["credit_cards"]
    assert len(cards) == 2
    deleted_flags = sorted(c["is_deleted"] for c in cards)
    assert deleted_flags == [False, True]
    for c in cards:
        assert "reviewed_at" not in c and "deleted_at" not in c and "user_acknowledged_at" not in c
        assert isinstance(c["review_findings"], list)


def test_list_only_own(client, db_session, seed_cc_refs):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    _make_card(db_session, user_a)
    headers_b = _auth(client, email="b@b.com")
    r = client.get("/credit-cards", headers=headers_b)
    assert r.json() == {"credit_cards": []}


def test_list_401(client, seed_cc_refs):
    assert client.get("/credit-cards").status_code == 401


# ---- GET /credit-cards/{id}/statements ----

def test_statements_order_desc(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    _make_statement(db_session, card, issue_year=2026, issue_month=4)
    _make_statement(db_session, card, issue_year=2026, issue_month=5)
    r = client.get(f"/credit-cards/{card.id}/statements", headers=headers)
    sts = r.json()["statements"]
    assert [(s["issue_year"], s["issue_month"]) for s in sts] == [(2026, 5), (2026, 4)]


def test_statements_404_other_user(client, db_session, seed_cc_refs):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a)
    headers_b = _auth(client, email="b@b.com")
    assert client.get(f"/credit-cards/{card.id}/statements", headers=headers_b).status_code == 404


def test_statements_soft_deleted_card(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user, deleted_at=datetime.now(timezone.utc))
    _make_statement(db_session, card)
    r = client.get(f"/credit-cards/{card.id}/statements", headers=headers)
    assert r.status_code == 200 and len(r.json()["statements"]) == 1


def test_statements_empty(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    r = client.get(f"/credit-cards/{card.id}/statements", headers=headers)
    assert r.json() == {"statements": []}


def test_statements_401(client, seed_cc_refs):
    import uuid
    assert client.get(f"/credit-cards/{uuid.uuid4()}/statements").status_code == 401


# ---- GET /credit-cards/{id}/statements/{statement_id}/items ----

def test_items_200(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card = _make_card(db_session, user)
    st = _make_statement(db_session, card)
    db_session.add_all([
        CreditCardStatementItem(credit_card_statement_id=st.id, charge_date=date(2026, 2, 2),
                                description="SPORTLINE", amount=Decimal("1997.50"), currency_id=1,
                                current_installment=3, total_installments=4, item_type_id=1),
        CreditCardStatementItem(credit_card_statement_id=st.id, charge_date=date(2026, 4, 29),
                                description="GOOGLE", amount=Decimal("69.99"), currency_id=1,
                                current_installment=None, total_installments=None, item_type_id=1),
    ])
    db_session.flush()
    r = client.get(f"/credit-cards/{card.id}/statements/{st.id}/items", headers=headers)
    items = r.json()["items"]
    assert len(items) == 2
    assert any(i["description"] == "SPORTLINE" and i["total_installments"] == 4 for i in items)
    assert any(i["description"] == "GOOGLE" and i["total_installments"] is None for i in items)


def test_items_404_other_user(client, db_session, seed_cc_refs):
    headers_a = _auth(client, email="a@b.com")
    user_a = _last_user(db_session)
    card = _make_card(db_session, user_a)
    st = _make_statement(db_session, card)
    headers_b = _auth(client, email="b@b.com")
    assert client.get(f"/credit-cards/{card.id}/statements/{st.id}/items", headers=headers_b).status_code == 404


def test_items_404_statement_of_other_card(client, db_session, seed_cc_refs):
    headers = _auth(client)
    user = _last_user(db_session)
    card1 = _make_card(db_session, user)
    card2 = _make_card(db_session, user, deleted_at=datetime.now(timezone.utc))  # soft para no chocar índice
    st2 = _make_statement(db_session, card2)
    # statement de card2 pedido bajo card1 -> 404
    assert client.get(f"/credit-cards/{card1.id}/statements/{st2.id}/items", headers=headers).status_code == 404


def test_items_401(client, seed_cc_refs):
    import uuid
    assert client.get(f"/credit-cards/{uuid.uuid4()}/statements/{uuid.uuid4()}/items").status_code == 401
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_read.py -q
```

- [ ] **Step 3: Crear el servicio** `app/services/credit_card_service.py`

```python
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.models.user import User


def list_credit_cards(db: Session, user: User) -> list[CreditCard]:
    return list(
        db.execute(
            select(CreditCard)
            .where(CreditCard.user_id == user.id)
            .order_by(CreditCard.created_at)
        ).scalars()
    )


def _require_card(db: Session, user: User, card_id: uuid.UUID) -> CreditCard:
    """La tarjeta del usuario (sin filtrar deleted_at: el historial se ve aunque esté soft-deleted)."""
    card = db.execute(
        select(CreditCard).where(CreditCard.id == card_id, CreditCard.user_id == user.id)
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)
    return card


def list_statements(db: Session, user: User, card_id: uuid.UUID) -> list[CreditCardStatement]:
    _require_card(db, user, card_id)
    return list(
        db.execute(
            select(CreditCardStatement)
            .where(CreditCardStatement.credit_card_id == card_id)
            .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
        ).scalars()
    )


def list_statement_items(
    db: Session, user: User, card_id: uuid.UUID, statement_id: uuid.UUID
) -> list[CreditCardStatementItem]:
    _require_card(db, user, card_id)
    statement = db.execute(
        select(CreditCardStatement).where(
            CreditCardStatement.id == statement_id,
            CreditCardStatement.credit_card_id == card_id,
        )
    ).scalar_one_or_none()
    if statement is None:
        raise AppError(ErrorCode.not_found)
    return list(
        db.execute(
            select(CreditCardStatementItem)
            .where(CreditCardStatementItem.credit_card_statement_id == statement_id)
            .order_by(CreditCardStatementItem.charge_date)
        ).scalars()
    )
```

- [ ] **Step 4: Crear el router** `app/routers/credit_cards.py`

```python
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.credit_card import CreditCardOut, StatementItemOut, StatementOut
from app.services import credit_card_service

router = APIRouter(tags=["credit-cards"])


@router.get("/credit-cards")
def list_credit_cards(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"credit_cards": [CreditCardOut.from_model(c) for c in credit_card_service.list_credit_cards(db, user)]}


@router.get("/credit-cards/{card_id}/statements")
def list_statements(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    sts = credit_card_service.list_statements(db, user, card_id)
    return {"statements": [StatementOut.from_model(s) for s in sts]}


@router.get("/credit-cards/{card_id}/statements/{statement_id}/items")
def list_statement_items(
    card_id: uuid.UUID,
    statement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = credit_card_service.list_statement_items(db, user, card_id, statement_id)
    return {"items": [StatementItemOut.from_model(it) for it in items]}
```

- [ ] **Step 5: Registrar el router en `app/main.py`** (agregar `credit_cards` al import de routers y
  `app.include_router(credit_cards.router)` junto a los demás).

- [ ] **Step 6: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_read.py -q
```

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/credit_card.py app/services/credit_card_service.py app/routers/credit_cards.py app/main.py tests/test_credit_cards_read.py && git commit -m "feat: credit-cards lectura (GET x3)"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (396 previos + los nuevos).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/credit-cards-lectura` a `main` (1 commit). Push **manual**. Post-cierre (lo hace el
  coordinador, no el implementer): actualizar las 3 páginas de Notion al envoltorio.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** GET /credit-cards (vacío, vigente+soft-deleted con is_deleted, solo del usuario,
  401); statements (orden desc, 404 otro usuario, soft-deleted ok, vacío, 401); items (200, 404 otro usuario,
  404 statement de otra tarjeta, 401). ✓
- **Sin placeholders:** schemas, servicio, router, registro y tests completos. El andamiaje de redacción en
  Step 1 está marcado para borrar; los tests válidos toman `(client, db_session, seed_cc_refs)`. ✓
- **Consistencia:** respuestas envueltas; `_require_card` sin filtro `deleted_at`; orden desc en statements,
  `charge_date` en items; `CreditCardOut` no expone metadata de ciclo ni `deleted_at` (solo `is_deleted`);
  reusa `seed_cc_refs` (Peso(1)+institución(1)+red(1)+tipo(1)+user) — alcanza para sembrar tarjetas. ✓

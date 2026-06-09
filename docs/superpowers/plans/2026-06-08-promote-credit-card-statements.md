# POST /credit-card-statements/promote — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar `POST /credit-card-statements/promote`: valida el staging, lo vuelca a las definitivas
(`credit_cards` + `credit_card_statements` + items + purchases), corre el reviewer de la tarjeta y el motor, y
borra el staging — todo en una transacción.

**Architecture:** Crece el router/servicio del recurso. `promote_staging_statement` en
`credit_card_statement_service.py`: 6 validaciones → 5 pasos de traspaso → reviewer (`review_credit_card`,
siempre) → motor (`materialize_credit_card`) → borrar staging → commit. Schema `PromoteResult`.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (TestClient).

**Spec:** `docs/superpowers/specs/2026-06-08-promote-credit-card-statements-design.md`

**Branch:** `feat/promote-credit-card-statements` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/promote-credit-card-statements
```

---

## Task 1: Error codes + schema

**Files:**
- Modify: `app/core/errors.py`
- Modify: `app/schemas/credit_card_statement.py`

- [ ] **Step 1: Agregar 5 codes** después de `statement_has_no_findings = (...)`:

```python
    statement_not_ready = (409, "El resumen tiene observaciones sin resolver.")
    items_incomplete = (409, "Hay ítems del resumen sin completar.")
    rates_required_new_card = (409, "Para dar de alta una tarjeta nueva, completá las tasas y el dato de IVA.")
    statement_period_exists = (409, "Ya cargaste un resumen de ese mes para esta tarjeta.")
    statement_period_not_after_last = (409, "Tenés que cargar el resumen siguiente al último que ya cargaste.")
```

- [ ] **Step 2: Agregar `PromoteResult`** al final de `app/schemas/credit_card_statement.py`:

```python
class PromoteResult(BaseModel):
    credit_card_id: uuid.UUID
    is_ready: bool
    review_findings: list[str]
```

---

## Task 2: Servicio + router + tests (TDD)

**Files:**
- Modify: `app/services/credit_card_statement_service.py`
- Modify: `app/routers/credit_card_statements.py`
- Test: `tests/test_promote_credit_card_statements.py` (nuevo)

- [ ] **Step 1: Escribir los tests (rojo)** — nuevo archivo `tests/test_promote_credit_card_statements.py`:

```python
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.credit_card import CreditCard
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.credit_card_purchase import CreditCardPurchase
from app.models.credit_card_statement import CreditCardStatement
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem
from app.models.user import User

from tests.test_credit_cards_model import _card_kwargs


@pytest.fixture
def cc_catalog(db_session, seed_uy_currency):
    db_session.add_all([
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True),
        Institution(id=1, country_code="UY", name="Scotiabank", visible=True),
        CreditCardNetwork(id=1, country_code="UY", code="amex", name="Amex"),
        CreditCardItemType(id=1, code="compra", name="Compra", description="x"),
        CreditCardItemType(id=2, code="interes", name="Interés", description="x"),
        CreditCardItemType(id=3, code="suscripcion", name="Suscripción", description="x"),
    ])
    db_session.flush()


def _auth(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _user(db_session):
    return db_session.execute(select(User)).scalars().first()


def _seed_ready_staging(db_session, user, items=None, **madre_over):
    fields = dict(
        user_id=user.id, institution_id=1, card_network_id=1,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25), current_limit=Decimal("180000.00"),
        total_local=Decimal("7991.28"), total_usd=Decimal("65.35"),
        minimum_payment_local=Decimal("600.00"), minimum_payment_usd=Decimal("0.00"),
        financing_rate_local=Decimal("69.98"), overdue_rate_local=Decimal("81.27"),
        financing_rate_usd=Decimal("13.50"), overdue_rate_usd=Decimal("15.68"),
        rates_add_vat=True, review_findings="[]", is_ready=True,
    )
    fields.update(madre_over)
    madre = StagingCreditCard(**fields)
    db_session.add(madre)
    db_session.flush()
    if items is None:
        items = [dict(charge_date=date(2026, 2, 2), description="SPORTLINE", amount=Decimal("1997.50"),
                      currency_id=1, current_installment=3, total_installments=4, item_type_id=1)]
    for it in items:
        db_session.add(StagingCreditCardItem(staging_credit_card_id=madre.id, **it))
    db_session.flush()
    return madre


def _cards(db_session, user):
    return db_session.execute(select(CreditCard).where(CreditCard.user_id == user.id)).scalars().all()


def test_promote_new_card(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user)
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["review_findings"] == ["closing_day_inferred"]
    assert body["is_ready"] is False
    cards = _cards(db_session, user)
    assert len(cards) == 1
    card = cards[0]
    assert card.closing_day == 13
    st = db_session.execute(select(CreditCardStatement).where(CreditCardStatement.credit_card_id == card.id)).scalars().all()
    assert len(st) == 1 and (st[0].issue_year, st[0].issue_month) == (2026, 5)
    # staging borrado
    assert db_session.execute(select(StagingCreditCard)).scalars().all() == []
    # motor no materializó (is_ready false)
    assert db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_type == "tarjeta_credito")
    ).scalars().all() == []


def test_promote_404_no_staging(client, cc_catalog):
    headers = _auth(client)
    assert client.post("/credit-card-statements/promote", json={}, headers=headers).status_code == 404


def test_promote_409_not_ready(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, is_ready=False, review_findings='["new_card"]')
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_not_ready"


def test_promote_409_incomplete_madre(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, closing_date=None)  # is_ready true pero falta closing_date
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_not_ready"


def test_promote_409_items_incomplete(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, items=[
        dict(charge_date=date(2026, 2, 2), description="X", amount=Decimal("1.00"),
             currency_id=1, current_installment=None, total_installments=None, item_type_id=None),  # falta tipo
    ])
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "items_incomplete"


def test_promote_409_rates_required_new_card(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, financing_rate_usd=None)  # tarjeta nueva, falta una tasa
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "rates_required_new_card"


def test_promote_409_period_exists(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=5,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user)  # mismo período 2026/5
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_period_exists"


def test_promote_409_period_not_after_last(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=6,
        closing_date=date(2026, 6, 13), due_date=date(2026, 6, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user)  # 2026/5, anterior al último 2026/6
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "statement_period_not_after_last"


def test_promote_existing_ready_materializes(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))  # closing_day 13, is_ready False de fábrica
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=4,
        closing_date=date(2026, 4, 13), due_date=date(2026, 4, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user)  # 2026/5, closing_day 13 == card.closing_day
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["review_findings"] == []
    assert r.json()["is_ready"] is True
    entries = db_session.execute(
        select(CashFlowEntry).where(CashFlowEntry.source_type == "tarjeta_credito")
    ).scalars().all()
    assert len(entries) >= 1  # el motor materializó


def test_promote_closing_day_changed(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))  # closing_day 13
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=4,
        closing_date=date(2026, 4, 13), due_date=date(2026, 4, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user, closing_date=date(2026, 5, 25))  # día 25 vs 13 -> dif 12
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.json()["review_findings"] == ["closing_day_changed"]
    assert r.json()["is_ready"] is False


def test_promote_identical_values_not_treated_as_new(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))  # created_at == updated_at (recién creada)
    db_session.add(card)
    db_session.flush()
    # staging con MISMOS current_limit/tasas que la tarjeta, período nuevo, mismo closing_day
    _seed_ready_staging(
        db_session, user,
        current_limit=Decimal("150000.00"),  # = _card_kwargs
        financing_rate_local=Decimal("69.98"), overdue_rate_local=Decimal("81.27"),
        financing_rate_usd=Decimal("13.50"), overdue_rate_usd=Decimal("15.68"), rates_add_vat=True,
    )
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert "closing_day_inferred" not in r.json()["review_findings"]  # no se la trató como nueva


def test_promote_reactivates_soft_deleted(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user), deleted_at=datetime(2026, 4, 1, tzinfo=timezone.utc))
    db_session.add(card)
    db_session.flush()
    _seed_ready_staging(db_session, user)
    r = client.post("/credit-card-statements/promote", json={}, headers=headers)
    assert r.status_code == 200
    db_session.refresh(card)
    assert card.deleted_at is None  # reactivada
    assert len(_cards(db_session, user)) == 1  # no se creó otra


def test_promote_rates_not_overwritten_on_update(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    card = CreditCard(**_card_kwargs(user))  # financing_rate_local 69.98
    db_session.add(card)
    db_session.flush()
    db_session.add(CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=4,
        closing_date=date(2026, 4, 13), due_date=date(2026, 4, 25),
        total_local=Decimal("1.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("0.00"), minimum_payment_usd=Decimal("0.00"),
    ))
    db_session.flush()
    _seed_ready_staging(db_session, user, financing_rate_local=None)  # NULL no debe pisar
    client.post("/credit-card-statements/promote", json={}, headers=headers)
    db_session.refresh(card)
    assert card.financing_rate_local == Decimal("69.98")


def test_promote_purchases(client, cc_catalog, db_session):
    headers = _auth(client)
    user = _user(db_session)
    _seed_ready_staging(db_session, user, items=[
        dict(charge_date=date(2026, 2, 2), description="HELADERA", amount=Decimal("100.00"),
             currency_id=1, current_installment=3, total_installments=12, item_type_id=1),  # cuotas -> purchase
        dict(charge_date=date(2026, 4, 29), description="GOOGLE", amount=Decimal("69.99"),
             currency_id=3, current_installment=None, total_installments=None, item_type_id=3),  # suscripción -> purchase
        dict(charge_date=date(2026, 5, 1), description="CAFE", amount=Decimal("5.00"),
             currency_id=1, current_installment=None, total_installments=None, item_type_id=1),  # un pago compra -> NO
    ])
    client.post("/credit-card-statements/promote", json={}, headers=headers)
    purchases = db_session.execute(select(CreditCardPurchase)).scalars().all()
    descs = {p.description for p in purchases}
    assert descs == {"HELADERA", "GOOGLE"}


def test_promote_401(client, cc_catalog):
    assert client.post("/credit-card-statements/promote", json={}).status_code == 401
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_promote_credit_card_statements.py -q
```

- [ ] **Step 3: Agregar al servicio** `app/services/credit_card_statement_service.py`. Imports nuevos:

```python
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.services.cash_flow.credit_cards import materialize_credit_card
from app.services.review.credit_cards import review_credit_card
```

(`CreditCard`, `CreditCardPurchase`, `CreditCardItemType`, `StagingCreditCardItem`, `datetime`, `timezone`,
`select`, `AppError`, `ErrorCode` ya están importados; `CreditCardStatement` y `CreditCardStatementItem`
—los definitivos— son nuevos en este módulo.)

Funciones nuevas (al final del módulo):

```python
_MADRE_REQUIRED = (
    "institution_id", "card_network_id", "closing_date", "due_date", "current_limit",
    "total_local", "total_usd", "minimum_payment_local", "minimum_payment_usd", "rates_add_vat",
)
_NEW_CARD_RATES = (
    "financing_rate_local", "overdue_rate_local", "financing_rate_usd", "overdue_rate_usd", "rates_add_vat",
)


def _staging_item_complete(it: StagingCreditCardItem) -> bool:
    if None in (it.charge_date, it.description, it.amount, it.currency_id, it.item_type_id):
        return False
    ci, ti = it.current_installment, it.total_installments
    if ci is None and ti is None:
        return True
    if ci is None or ti is None:
        return False
    return ci >= 1 and ti >= 1 and ci <= ti


def _resolve_existing_card(db: Session, user_id, institution_id, card_network_id):
    """La vigente si hay; si no, una soft-deleted; None si ninguna."""
    card = db.execute(
        select(CreditCard).where(
            CreditCard.user_id == user_id,
            CreditCard.institution_id == institution_id,
            CreditCard.card_network_id == card_network_id,
            CreditCard.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if card is not None:
        return card
    return db.execute(
        select(CreditCard)
        .where(
            CreditCard.user_id == user_id,
            CreditCard.institution_id == institution_id,
            CreditCard.card_network_id == card_network_id,
            CreditCard.deleted_at.is_not(None),
        )
        .order_by(CreditCard.deleted_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _upsert_purchases(
    db: Session, card: CreditCard, madre: StagingCreditCard, items: list[StagingCreditCardItem]
) -> None:
    sub_id = db.execute(
        select(CreditCardItemType.id).where(CreditCardItemType.code == "suscripcion")
    ).scalar_one_or_none()
    for it in items:
        if it.total_installments is not None:  # con cuotas: por clave
            existing = db.execute(
                select(CreditCardPurchase).where(
                    CreditCardPurchase.credit_card_id == card.id,
                    CreditCardPurchase.charge_date == it.charge_date,
                    CreditCardPurchase.description == it.description,
                    CreditCardPurchase.total_installments == it.total_installments,
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.last_statement_closing_date = madre.closing_date
                existing.item_type_id = it.item_type_id
                continue
        elif not (sub_id is not None and it.item_type_id == sub_id):
            continue  # sin cuotas y no suscripción -> no califica
        db.add(
            CreditCardPurchase(
                credit_card_id=card.id,
                description=it.description,
                charge_date=it.charge_date,
                amount=it.amount,
                currency_id=it.currency_id,
                total_installments=it.total_installments,
                item_type_id=it.item_type_id,
                last_statement_closing_date=madre.closing_date,
            )
        )


def promote_staging_statement(db: Session, user: User) -> CreditCard:
    madre = db.execute(
        select(StagingCreditCard).where(StagingCreditCard.user_id == user.id).with_for_update()
    ).scalar_one_or_none()
    if madre is None:
        raise AppError(ErrorCode.not_found)

    # 2. madre lista + completa (guarda defensiva de completitud)
    if not madre.is_ready or any(getattr(madre, f) is None for f in _MADRE_REQUIRED):
        raise AppError(ErrorCode.statement_not_ready)

    # 3. ítems completos
    items = list(
        db.execute(
            select(StagingCreditCardItem).where(
                StagingCreditCardItem.staging_credit_card_id == madre.id
            )
        ).scalars()
    )
    if any(not _staging_item_complete(it) for it in items):
        raise AppError(ErrorCode.items_incomplete)

    # 4. tarjeta nueva -> tasas obligatorias
    card = _resolve_existing_card(db, user.id, madre.institution_id, madre.card_network_id)
    is_new = card is None
    if is_new and any(getattr(madre, f) is None for f in _NEW_CARD_RATES):
        raise AppError(ErrorCode.rates_required_new_card)

    issue_year, issue_month = madre.closing_date.year, madre.closing_date.month

    if not is_new:
        # 5. período duplicado
        if db.execute(
            select(CreditCardStatement.id).where(
                CreditCardStatement.credit_card_id == card.id,
                CreditCardStatement.issue_year == issue_year,
                CreditCardStatement.issue_month == issue_month,
            )
        ).first() is not None:
            raise AppError(ErrorCode.statement_period_exists)
        # 6. período posterior al último
        last = db.execute(
            select(CreditCardStatement.issue_year, CreditCardStatement.issue_month)
            .where(CreditCardStatement.credit_card_id == card.id)
            .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
            .limit(1)
        ).first()
        if last is not None and (issue_year, issue_month) <= (last.issue_year, last.issue_month):
            raise AppError(ErrorCode.statement_period_not_after_last)

    # Paso 1: UPSERT credit_cards
    if is_new:
        card = CreditCard(
            user_id=user.id,
            institution_id=madre.institution_id,
            card_network_id=madre.card_network_id,
            current_limit=madre.current_limit,
            closing_day=madre.closing_date.day,
            financing_rate_local=madre.financing_rate_local,
            overdue_rate_local=madre.overdue_rate_local,
            financing_rate_usd=madre.financing_rate_usd,
            overdue_rate_usd=madre.overdue_rate_usd,
            rates_add_vat=madre.rates_add_vat,
            review_findings="[]",
            is_ready=False,
        )
        db.add(card)
        db.flush()
    else:
        card.deleted_at = None  # reactiva si estaba soft-deleted
        card.current_limit = madre.current_limit
        if madre.financing_rate_local is not None:
            card.financing_rate_local = madre.financing_rate_local
        if madre.overdue_rate_local is not None:
            card.overdue_rate_local = madre.overdue_rate_local
        if madre.financing_rate_usd is not None:
            card.financing_rate_usd = madre.financing_rate_usd
        if madre.overdue_rate_usd is not None:
            card.overdue_rate_usd = madre.overdue_rate_usd
        if madre.rates_add_vat is not None:
            card.rates_add_vat = madre.rates_add_vat
        # explícito: garantiza created_at != updated_at (no se trata como nueva)
        card.updated_at = datetime.now(timezone.utc)
        db.flush()

    # Paso 2: INSERT credit_card_statements
    statement = CreditCardStatement(
        credit_card_id=card.id,
        issue_year=issue_year,
        issue_month=issue_month,
        closing_date=madre.closing_date,
        due_date=madre.due_date,
        total_local=madre.total_local,
        total_usd=madre.total_usd,
        minimum_payment_local=madre.minimum_payment_local,
        minimum_payment_usd=madre.minimum_payment_usd,
    )
    db.add(statement)
    db.flush()

    # Paso 3: INSERT credit_card_statement_items
    for it in items:
        db.add(
            CreditCardStatementItem(
                credit_card_statement_id=statement.id,
                charge_date=it.charge_date,
                description=it.description,
                amount=it.amount,
                currency_id=it.currency_id,
                current_installment=it.current_installment,
                total_installments=it.total_installments,
                item_type_id=it.item_type_id,
            )
        )
    db.flush()

    # Paso 4: purchases
    _upsert_purchases(db, card, madre, items)

    # reviewer (siempre) + motor
    review_credit_card(db, card.id)
    materialize_credit_card(db, card.id)

    # cierre: borrar el staging (ítems por cascade)
    db.delete(madre)
    db.commit()
    db.refresh(card)
    return card
```

- [ ] **Step 4: Agregar el endpoint al router** `app/routers/credit_card_statements.py`. Sumar `PromoteResult`
  al import de schemas y el endpoint:

```python
from app.schemas.credit_card_statement import (  # PromoteResult es nuevo en esta lista
    ...,
    PromoteResult,
)


@router.post("/credit-card-statements/promote", response_model=PromoteResult)
def promote_staging_statement(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PromoteResult:
    card = credit_card_statement_service.promote_staging_statement(db, user)
    return PromoteResult(
        credit_card_id=card.id,
        is_ready=card.is_ready,
        review_findings=json.loads(card.review_findings),
    )
```

(Agregar `import json` al router si no está.)

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_promote_credit_card_statements.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/schemas/credit_card_statement.py app/services/credit_card_statement_service.py app/routers/credit_card_statements.py tests/test_promote_credit_card_statements.py && git commit -m "feat: POST /credit-card-statements/promote"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (381 previos + los nuevos del promote).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/promote-credit-card-statements` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** new card (happy path, motor no-op), 404, statement_not_ready (×2: is_ready false +
  madre incompleta), items_incomplete, rates_required_new_card, statement_period_exists,
  statement_period_not_after_last, existente lista (motor materializa), closing_day_changed, valores idénticos
  no-nueva, reactivación soft-deleted, tasas no pisan, purchases (cuotas/suscripción/un-pago), 401. ✓
- **Sin placeholders:** codes, schema, servicio (validaciones + 5 pasos + reviewer + motor + borrado) y tests
  completos. ✓
- **Consistencia:** `updated_at=now()` explícito en la rama existente; reviewer **siempre** tras el statement;
  motor después del reviewer (respeta is_ready); `_resolve_existing_card` prioriza vigente; purchases por
  clave/always-create; staging borrado al final; `user_id` del token. `CreditCardStatement` y
  `CreditCardStatementItem` (definitivos) se importan al tope del módulo (nuevos). ✓

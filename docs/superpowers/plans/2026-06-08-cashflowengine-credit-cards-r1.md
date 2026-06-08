# CashFlowEngine.credit_cards — Slice 1 (Responsabilidad 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar `materialize_credit_card` con el gate `is_ready`, la **Responsabilidad 1** (materializar
el último resumen, hasta 2 filas por moneda) y la reconciliación por clave lógica (UPSERT + borrado de futuras
sin pago real). Slice 1 de 2.

**Architecture:** `app/services/cash_flow/credit_cards.py`, espejando `materialize_debt`: lock de la tarjeta,
gate, target set reconciliado contra la clave `(source_type, source_id, issue_year, issue_month, currency_id)`,
borrado acotado a futuras sin pago real, `db.flush()`. La reconciliación vive en `_reconcile(db, card,
targets, today)` para que el slice 2 (R2) sólo agrande `targets`. Helper de moneda USD en `scoping.py`.

**Tech Stack:** SQLAlchemy 2.0 · pytest · Postgres (`margin_test`).

**Spec:** `docs/superpowers/specs/2026-06-08-cashflowengine-credit-cards-design.md`

**Branch:** `feat/cashflow-credit-cards-r1` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git `git add`/`git commit` planos. No push.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `app/services/scoping.py` | + `credit_card_usd_currency(db, user)` |
| `app/services/cash_flow/credit_cards.py` | `materialize_credit_card`, `_latest_statement`, `_reconcile` |
| `tests/test_cashflow_credit_cards.py` | Tests de gate + R1 + reconciliación |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/cashflow-credit-cards-r1
```

---

## Task 1: Helper de moneda USD (`scoping.py`)

**Files:**
- Modify: `app/services/scoping.py`

- [ ] **Step 1: Agregar el helper** (después de `legal_tender_currency`)

```python
def credit_card_usd_currency(db: Session, user: User) -> Currency:
    """Moneda USD del país del usuario para tarjetas: allowed_in_credit_card y no de curso legal.
    Se deriva del catálogo (no del body)."""
    return db.execute(
        select(Currency).where(
            Currency.country_code == user.country_code,
            Currency.allowed_in_credit_card.is_(True),
            Currency.is_legal_tender.is_(False),
        )
    ).scalars().first()
```

(No requiere imports nuevos: `select`, `Session`, `Currency`, `User` ya están en el módulo.)

---

## Task 2: Motor — gate + R1 + reconciliación (TDD)

**Files:**
- Create: `app/services/cash_flow/credit_cards.py`
- Test: `tests/test_cashflow_credit_cards.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_cashflow_credit_cards.py
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.currency import Currency
from app.services.cash_flow.credit_cards import materialize_credit_card
from app.services.scoping import credit_card_usd_currency

from tests.test_credit_cards_model import _card_kwargs

TODAY = date(2026, 5, 1)


@pytest.fixture
def user_uy(db_session, seed_cc_refs):
    # seed_cc_refs ya siembra Peso (id 1). Agregamos el USD (Dólar id 3).
    db_session.add(
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True)
    )
    db_session.flush()
    return seed_cc_refs


def _make_card(db_session, user, **over):
    kwargs = _card_kwargs(user)  # rates _local/_usd seteadas, closing_day 13, is_ready False
    kwargs["is_ready"] = True
    kwargs.update(over)
    card = CreditCard(**kwargs)
    db_session.add(card)
    db_session.flush()
    return card


def _make_statement(db_session, card, *, issue_year=2026, issue_month=5, closing_day=13, due_day=25,
                    total_local=Decimal("7991.28"), total_usd=Decimal("65.35"),
                    min_local=Decimal("600.00"), min_usd=Decimal("0.00")):
    st = CreditCardStatement(
        credit_card_id=card.id,
        issue_year=issue_year,
        issue_month=issue_month,
        closing_date=date(issue_year, issue_month, closing_day),
        due_date=date(issue_year, issue_month, due_day),
        total_local=total_local,
        total_usd=total_usd,
        minimum_payment_local=min_local,
        minimum_payment_usd=min_usd,
    )
    db_session.add(st)
    db_session.flush()
    return st


def _orm_entries(db_session, card):
    from sqlalchemy import select

    return list(
        db_session.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.source_id == card.id,
            )
        ).scalars()
    )


def test_usd_currency_helper(db_session, user_uy):
    assert credit_card_usd_currency(db_session, user_uy).id == 3


def test_gate_not_ready_writes_nothing(db_session, user_uy):
    card = _make_card(db_session, user_uy, is_ready=False)
    _make_statement(db_session, card)
    materialize_credit_card(db_session, card.id, today=TODAY)
    assert _orm_entries(db_session, card) == []


def test_missing_card_is_noop(db_session, user_uy):
    materialize_credit_card(db_session, uuid.uuid4(), today=TODAY)  # no existe -> sin error


def test_two_currencies(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card)
    materialize_credit_card(db_session, card.id, today=TODAY)
    entries = {e.currency_id: e for e in _orm_entries(db_session, card)}
    assert set(entries) == {1, 3}
    local = entries[1]
    assert local.amount == Decimal("7991.28")
    assert local.event_date == date(2026, 5, 25)
    assert (local.issue_year, local.issue_month) == (2026, 5)
    assert local.minimum_payment == Decimal("600.00")
    assert local.is_income is False
    assert local.financing_rate == Decimal("85.38")  # 69.98 * 1.22
    assert local.overdue_rate == Decimal("99.15")    # 81.27 * 1.22
    usd = entries[3]
    assert usd.amount == Decimal("65.35")
    assert usd.minimum_payment == Decimal("0.00")
    assert usd.financing_rate == Decimal("16.47")  # 13.50 * 1.22
    assert usd.overdue_rate == Decimal("19.13")    # 15.68 * 1.22


def test_zero_usd_total_only_local(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card, total_usd=Decimal("0.00"))
    materialize_credit_card(db_session, card.id, today=TODAY)
    entries = _orm_entries(db_session, card)
    assert len(entries) == 1
    assert entries[0].currency_id == 1


def test_reconcile_updates_not_duplicates(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    st = _make_statement(db_session, card, total_local=Decimal("100.00"), total_usd=Decimal("0.00"))
    materialize_credit_card(db_session, card.id, today=TODAY)
    st.total_local = Decimal("200.00")
    db_session.flush()
    materialize_credit_card(db_session, card.id, today=TODAY)
    entries = _orm_entries(db_session, card)
    assert len(entries) == 1
    assert entries[0].amount == Decimal("200.00")


def test_currency_that_lost_total_is_deleted(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    st = _make_statement(db_session, card, total_usd=Decimal("65.35"))
    materialize_credit_card(db_session, card.id, today=TODAY)
    assert any(e.currency_id == 3 for e in _orm_entries(db_session, card))
    st.total_usd = Decimal("0.00")
    db_session.flush()
    materialize_credit_card(db_session, card.id, today=TODAY)
    cids = {e.currency_id for e in _orm_entries(db_session, card)}
    assert cids == {1}  # la fila USD futura se borró


def test_no_delete_when_real_payment(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    st = _make_statement(db_session, card, total_usd=Decimal("65.35"))
    materialize_credit_card(db_session, card.id, today=TODAY)
    usd = next(e for e in _orm_entries(db_session, card) if e.currency_id == 3)
    db_session.add(CashFlowPayment(cash_flow_entry_id=usd.id, amount=Decimal("10.00"), plan_id=None))
    db_session.flush()
    st.total_usd = Decimal("0.00")
    db_session.flush()
    with pytest.raises(RuntimeError):
        materialize_credit_card(db_session, card.id, today=TODAY)


def test_past_entry_not_touched(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card)  # último: 2026/5
    # entry pasada (2026/3) fuera del target, event_date < today
    past = CashFlowEntry(
        user_id=card.user_id,
        event_date=date(2026, 3, 25),
        is_income=False,
        amount=Decimal("500.00"),
        currency_id=1,
        issue_year=2026,
        issue_month=3,
        source_type="tarjeta_credito",
        source_id=card.id,
    )
    db_session.add(past)
    db_session.flush()
    materialize_credit_card(db_session, card.id, today=TODAY)
    keys = {(e.issue_year, e.issue_month, e.currency_id) for e in _orm_entries(db_session, card)}
    assert (2026, 3, 1) in keys  # la pasada sigue
```

- [ ] **Step 2: Run → rojo** (`ModuleNotFoundError: app.services.cash_flow.credit_cards`)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py -q
```

- [ ] **Step 3: Crear el motor**

```python
# app/services/cash_flow/credit_cards.py
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.country import Country
from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.user import User
from app.services.cash_flow.rates import effective_rate
from app.services.scoping import credit_card_usd_currency, legal_tender_currency

HORIZON = date(2027, 12, 31)


def _latest_statement(db: Session, credit_card_id: uuid.UUID) -> CreditCardStatement | None:
    """El resumen de mayor (issue_year, issue_month) de la tarjeta. None si no hay."""
    return db.execute(
        select(CreditCardStatement)
        .where(CreditCardStatement.credit_card_id == credit_card_id)
        .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
        .limit(1)
    ).scalar_one_or_none()


def _reconcile(
    db: Session, card: CreditCard, targets: dict[tuple[int, int, int], dict], today: date
) -> None:
    """UPSERT del target set por clave (issue_year, issue_month, currency_id) contra las entries
    'tarjeta_credito' de la tarjeta; borra las que quedan fuera solo si son futuras y sin pago real."""
    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.source_id == card.id,
            )
        ).scalars()
    )
    by_key = {(e.issue_year, e.issue_month, e.currency_id): e for e in existing}

    for (iy, im, cid), f in targets.items():
        entry = by_key.get((iy, im, cid))
        if entry is not None:
            entry.event_date = f["event_date"]
            entry.amount = f["amount"]
            entry.financing_rate = f["financing_rate"]
            entry.overdue_rate = f["overdue_rate"]
            entry.minimum_payment = f["minimum_payment"]
        else:
            db.add(
                CashFlowEntry(
                    user_id=card.user_id,
                    event_date=f["event_date"],
                    is_income=False,
                    amount=f["amount"],
                    currency_id=cid,
                    financing_rate=f["financing_rate"],
                    overdue_rate=f["overdue_rate"],
                    issue_year=iy,
                    issue_month=im,
                    minimum_payment=f["minimum_payment"],
                    source_type="tarjeta_credito",
                    source_id=card.id,
                )
            )

    stale = [e for key, e in by_key.items() if key not in targets]
    if stale:
        paid_ids = set(
            db.execute(
                select(CashFlowPayment.cash_flow_entry_id).where(
                    CashFlowPayment.cash_flow_entry_id.in_([e.id for e in stale]),
                    CashFlowPayment.plan_id.is_(None),
                )
            ).scalars()
        )
        for e in stale:
            if e.event_date is not None and e.event_date >= today:
                if e.id in paid_ids:
                    raise RuntimeError(
                        f"materialize_credit_card: invariante violado, "
                        f"entry {e.id} con pago real quedó fuera del objetivo"
                    )
                db.delete(e)


def materialize_credit_card(
    db: Session, credit_card_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de una tarjeta. Gate: is_ready False → no-op. No commit.
    Responsabilidad 1: materializa el último resumen (hasta una fila por moneda con total > 0)."""
    if today is None:
        today = date.today()

    card = db.execute(
        select(CreditCard).where(CreditCard.id == credit_card_id).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        return
    if not card.is_ready:
        return  # gate: no-op silencioso

    user = db.get(User, card.user_id)
    vat_rate = db.get(Country, user.country_code).vat_rate
    local_id = legal_tender_currency(db, user).id
    usd_id = credit_card_usd_currency(db, user).id

    fin_local = effective_rate(card.financing_rate_local, card.rates_add_vat, vat_rate)
    over_local = effective_rate(card.overdue_rate_local, card.rates_add_vat, vat_rate)
    fin_usd = effective_rate(card.financing_rate_usd, card.rates_add_vat, vat_rate)
    over_usd = effective_rate(card.overdue_rate_usd, card.rates_add_vat, vat_rate)

    targets: dict[tuple[int, int, int], dict] = {}

    # --- Responsabilidad 1: el último resumen ---
    statement = _latest_statement(db, card.id)
    if statement is not None:
        iy, im = statement.closing_date.year, statement.closing_date.month
        for cid, total, minimum, fin, over in (
            (local_id, statement.total_local, statement.minimum_payment_local, fin_local, over_local),
            (usd_id, statement.total_usd, statement.minimum_payment_usd, fin_usd, over_usd),
        ):
            if total is not None and total > 0:
                targets[(iy, im, cid)] = dict(
                    event_date=statement.due_date,
                    amount=total,
                    financing_rate=fin,
                    overdue_rate=over,
                    minimum_payment=minimum,
                )

    _reconcile(db, card, targets, today)
    db.flush()
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/scoping.py app/services/cash_flow/credit_cards.py tests/test_cashflow_credit_cards.py && git commit -m "feat: CashFlowEngine.credit_cards R1 (materializar último resumen)"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (325 previos + los nuevos del motor R1).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/cashflow-credit-cards-r1` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec (slice 1):** gate (not ready / inexistente), 2 monedas con todos los campos y tasas
  efectivas, total 0 → sin fila, UPSERT (update no duplica), borrado de moneda que perdió total, no-borrar con
  pago real (RuntimeError), pasado intacto, y el helper USD. ✓
- **Sin placeholders:** código del helper, el motor y el test file completos. ✓
- **Layering:** `_reconcile(db, card, targets, today)` recibe el target set; el slice 2 sólo agregará entradas
  a `targets` antes de llamarlo, sin tocar la reconciliación. ✓
- **Consistencia:** rates NOT NULL en `credit_cards` → las entries de tarjeta siempre llevan tasa (no hay test
  de tasa NULL, a diferencia de `debts`). vat_rate UY = 22 → 69.98×1.22=85.38 (ROUND_HALF_UP), coincide con el
  ejemplo de Notion. ✓

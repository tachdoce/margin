# CashFlowEngine.credit_cards — Slice 2 (Responsabilidad 2: proyección) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Extender `materialize_credit_card` con la **Responsabilidad 2**: proyectar los meses siguientes
(cuotas pendientes + suscripciones) a partir de los ítems del último resumen, agrupados por mes/moneda, y
sumarlos al target set que ya reconcilia el slice 1. Slice 2 de 2.

**Architecture:** Se agregan helpers `_add_months` y `_projection_sums` a
`app/services/cash_flow/credit_cards.py`. `materialize_credit_card` calcula las proyecciones (de `M+1` al
horizonte, donde `M` = mes del `closing_date` del último resumen) y las agrega a `targets` antes de llamar a
`_reconcile` (que NO cambia: ya reconcilia "el target set" y borra futuras sin pago real). Así una proyección
se vuelve real cuando llega su resumen (R1 la pisa por clave) y las que dejan de corresponder se borran.

**Tech Stack:** SQLAlchemy 2.0 · pytest · Postgres (`margin_test`).

**Spec:** `docs/superpowers/specs/2026-06-08-cashflowengine-credit-cards-design.md` (§5, §6, §8 slice 2).

**Branch:** `feat/cashflow-credit-cards-r2` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow/credit_cards.py` | + `_add_months`, `_projection_sums`; `materialize_credit_card` agrega R2 al target set + imports nuevos |
| `tests/test_cashflow_credit_cards.py` | + fixture `sub_type`, helper `_add_item`, tests de R2 |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/cashflow-credit-cards-r2
```

---

## Task 1: Proyección (R2) — TDD

**Files:**
- Modify: `app/services/cash_flow/credit_cards.py`
- Modify: `tests/test_cashflow_credit_cards.py`

- [ ] **Step 1: Agregar los tests (rojo)** — añadir al final de `tests/test_cashflow_credit_cards.py`. Antes,
  agregar estos imports arriba (junto a los existentes):

```python
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_statement_item import CreditCardStatementItem
```

Y al final del archivo:

```python
@pytest.fixture
def sub_type(db_session, user_uy):
    """Agrega el tipo de ítem 'suscripcion' (id 3). Devuelve su id. Reusa user_uy."""
    db_session.add(
        CreditCardItemType(id=3, code="suscripcion", name="Suscripción", description="x")
    )
    db_session.flush()
    return 3


def _add_item(db_session, statement, *, amount, currency_id, item_type_id,
              current_installment=None, total_installments=None,
              charge_date=date(2026, 2, 2), description="X"):
    item = CreditCardStatementItem(
        credit_card_statement_id=statement.id,
        charge_date=charge_date,
        description=description,
        amount=amount,
        currency_id=currency_id,
        current_installment=current_installment,
        total_installments=total_installments,
        item_type_id=item_type_id,
    )
    db_session.add(item)
    db_session.flush()
    return item


def _by_key(db_session, card):
    return {(e.issue_year, e.issue_month, e.currency_id): e for e in _orm_entries(db_session, card)}


def test_pending_installment_projects_remaining_months(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))  # solo local en R1
    _add_item(db_session, st, amount=Decimal("1997.50"), currency_id=1, item_type_id=1,
              current_installment=3, total_installments=4)  # 3/4 -> falta 1 (junio)
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    keys = _by_key(db_session, card)
    assert (2026, 6, 1) in keys
    junio = keys[(2026, 6, 1)]
    assert junio.amount == Decimal("1997.50")
    assert junio.event_date == date(2026, 6, 13)
    assert junio.minimum_payment is None
    assert (2026, 7, 1) not in keys  # no hay más cuotas


def test_subscription_projects_every_month(db_session, user_uy, sub_type):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("69.99"), currency_id=3, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    usd_months = sorted(m for (y, m, c) in _by_key(db_session, card) if c == 3)
    assert usd_months == [6, 7, 8, 9, 10, 11, 12]  # junio..diciembre
    sample = _by_key(db_session, card)[(2026, 7, 3)]
    assert sample.amount == Decimal("69.99")
    assert sample.event_date == date(2026, 7, 13)
    assert sample.minimum_payment is None


def test_one_payment_not_projected(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("500.00"), currency_id=1, item_type_id=1)  # sin cuotas, compra
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    future = [(y, m) for (y, m, c) in _by_key(db_session, card) if (y, m) != (2026, 5)]
    assert future == []  # solo el resumen de mayo (R1), nada proyectado


def test_grouping_sums_same_month_currency(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("100.00"), currency_id=1, item_type_id=1,
              current_installment=1, total_installments=2)  # -> junio
    _add_item(db_session, st, amount=Decimal("50.00"), currency_id=1, item_type_id=1,
              current_installment=1, total_installments=2)  # -> junio
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    assert _by_key(db_session, card)[(2026, 6, 1)].amount == Decimal("150.00")


def test_closing_day_clamped_in_projection(db_session, user_uy, sub_type):
    card = _make_card(db_session, user_uy, closing_day=31)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_item(db_session, st, amount=Decimal("69.99"), currency_id=3, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 6, 30))
    assert _by_key(db_session, card)[(2026, 6, 3)].event_date == date(2026, 6, 30)  # junio no tiene 31


def test_projection_becomes_real(db_session, user_uy, sub_type):
    card = _make_card(db_session, user_uy, closing_day=13)
    st_apr = _make_statement(db_session, card, issue_year=2026, issue_month=4, closing_day=13, due_day=25,
                             total_local=Decimal("1000.00"), total_usd=Decimal("0.00"),
                             min_local=Decimal("100.00"))
    _add_item(db_session, st_apr, amount=Decimal("100.00"), currency_id=1, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=date(2026, 4, 1), horizon=date(2026, 12, 31))
    # mayo quedó proyectado (suscripción), minimum_payment NULL
    proj_may = _by_key(db_session, card)[(2026, 5, 1)]
    assert proj_may.minimum_payment is None
    assert proj_may.amount == Decimal("100.00")
    # llega el resumen real de mayo
    st_may = _make_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=13, due_day=25,
                             total_local=Decimal("5000.00"), total_usd=Decimal("0.00"),
                             min_local=Decimal("300.00"))
    _add_item(db_session, st_may, amount=Decimal("100.00"), currency_id=1, item_type_id=sub_type)
    materialize_credit_card(db_session, card.id, today=date(2026, 5, 1), horizon=date(2026, 12, 31))
    keys = _by_key(db_session, card)
    real_may = keys[(2026, 5, 1)]
    assert real_may.amount == Decimal("5000.00")     # pisada por R1
    assert real_may.minimum_payment == Decimal("300.00")
    assert real_may.event_date == date(2026, 5, 25)
    # no se duplicó: una sola entry para (2026, 5, 1)
    assert sum(1 for (y, m, c) in keys if (y, m, c) == (2026, 5, 1)) == 1


def test_reprojection_deletes_stale_future(db_session, user_uy):
    card = _make_card(db_session, user_uy, closing_day=13)
    st = _make_statement(db_session, card, total_usd=Decimal("0.00"))
    item = _add_item(db_session, st, amount=Decimal("100.00"), currency_id=1, item_type_id=1,
                     current_installment=1, total_installments=3)  # falta 2 -> junio, julio
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    keys = _by_key(db_session, card)
    assert (2026, 6, 1) in keys and (2026, 7, 1) in keys
    item.current_installment = 3  # ya no faltan cuotas
    db_session.flush()
    materialize_credit_card(db_session, card.id, today=TODAY, horizon=date(2026, 12, 31))
    keys = _by_key(db_session, card)
    assert (2026, 6, 1) not in keys and (2026, 7, 1) not in keys  # proyecciones futuras borradas
```

- [ ] **Step 2: Run → rojo** (las proyecciones no existen aún)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py -q
```

- [ ] **Step 3: Implementar R2 en `app/services/cash_flow/credit_cards.py`**

Agregar imports (junto a los existentes):

```python
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.services.cash_flow.date_utils import compute_event_date
```

Agregar el helper `_add_months` (después de `HORIZON`):

```python
def _add_months(year: int, month: int, k: int) -> tuple[int, int]:
    """(year, month) + k meses."""
    idx = (month - 1) + k
    return year + idx // 12, idx % 12 + 1
```

Agregar el helper `_projection_sums` (después de `_latest_statement`):

```python
def _projection_sums(
    db: Session, statement: CreditCardStatement, horizon: date
) -> dict[tuple[int, int, int], Decimal]:
    """{(year, month, currency_id): monto} de cuotas pendientes + suscripciones de los ítems del
    resumen, de M+1 (M = mes del closing_date) al horizonte, agrupadas por mes y moneda."""
    sub_type_id = db.execute(
        select(CreditCardItemType.id).where(CreditCardItemType.code == "suscripcion")
    ).scalar_one_or_none()
    items = db.execute(
        select(CreditCardStatementItem).where(
            CreditCardStatementItem.credit_card_statement_id == statement.id
        )
    ).scalars()

    base_y, base_m = statement.closing_date.year, statement.closing_date.month
    horizon_key = (horizon.year, horizon.month)
    sums: dict[tuple[int, int, int], Decimal] = {}

    def add(k: int, currency_id: int, amount: Decimal) -> bool:
        y, m = _add_months(base_y, base_m, k)
        if (y, m) > horizon_key:
            return False
        key = (y, m, currency_id)
        sums[key] = sums.get(key, Decimal("0")) + amount
        return True

    for item in items:
        if item.current_installment is not None and item.total_installments is not None:
            remaining = item.total_installments - item.current_installment
            for k in range(1, remaining + 1):
                if not add(k, item.currency_id, item.amount):
                    break
        elif sub_type_id is not None and item.item_type_id == sub_type_id:
            k = 1
            while add(k, item.currency_id, item.amount):
                k += 1

    return sums
```

Importar `Decimal` arriba si no está:

```python
from decimal import Decimal
```

En `materialize_credit_card`, después del bloque de Responsabilidad 1 (y antes de `_reconcile`), agregar la
Responsabilidad 2:

```python
    # --- Responsabilidad 2: proyección de meses siguientes ---
    if statement is not None:
        rate_pair = {local_id: (fin_local, over_local), usd_id: (fin_usd, over_usd)}
        for (y, m, cid), amount in _projection_sums(db, statement, horizon).items():
            fin, over = rate_pair.get(cid, (None, None))
            targets[(y, m, cid)] = dict(
                event_date=compute_event_date(y, m, card.closing_day, False),
                amount=amount,
                financing_rate=fin,
                overdue_rate=over,
                minimum_payment=None,
            )

    _reconcile(db, card, targets, today)
    db.flush()
```

(La línea `_reconcile(...)` + `db.flush()` ya existía: reemplazar el bloque final para que R2 quede **antes**
de la reconciliación. R1 cubre el mes `M` y R2 los `M+1..horizonte`, así que no hay colisión de claves dentro
de una corrida.)

- [ ] **Step 4: Run → verde** (tests nuevos + los de slice 1)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_credit_cards.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/credit_cards.py tests/test_cashflow_credit_cards.py && git commit -m "feat: CashFlowEngine.credit_cards R2 (proyección de meses siguientes)"
```

---

## Task 2: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (334 previos + los nuevos de R2).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/cashflow-credit-cards-r2` a `main` (1 commit). Push **manual**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec (slice 2):** cuota pendiente (proyecta los meses que faltan), suscripción (todos los
  meses al horizonte), compra de un pago (no proyecta), agrupación mes/moneda (suma), clamp de `closing_day`,
  convivencia proyección→real (R1 pisa por clave, sin duplicar), reproyección que borra futuras sobrantes. ✓
- **Sin placeholders:** imports, helpers, el bloque R2 de `materialize_credit_card` y los tests completos. ✓
- **Layering:** `_reconcile` no cambia; R2 sólo agranda `targets`. R1 (mes M) y R2 (M+1..) no colisionan. ✓
- **Consistencia:** `_projection_sums` usa `item.amount` (NOT NULL en ítems promovidos); suscripción por
  `code`; rates por moneda vía `rate_pair`; `compute_event_date(..., shift_weekends=False)` clampa sin correr
  finde; bound del horizonte por `(year, month)`. ✓

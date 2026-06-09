# CashFlowEngine — piso = primer día del mes actual — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Que los motores `incomes`/`expenses`/`debts` materialicen la entry del **mes actual** aunque el día
nominal ya haya pasado. El piso pasa de `today` a `today.replace(day=1)` (primer día del mes), en la generación
de targets y en el borrado de stale.

**Architecture:** Cambio mecánico e idéntico en los 3 motores: definir `month_start = today.replace(day=1)` y
usarlo donde hoy se usa `today` como cota inferior de fecha. Se mantiene la protección de pagos reales.

**Tech Stack:** SQLAlchemy 2.0 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-09-cashflow-current-month-floor-design.md`

**Branch:** `feat/cashflow-current-month-floor` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push. **No tocar Notion** (el usuario lo deprecó como
guía).

**Patrón a aplicar en cada motor (`app/services/cash_flow/{incomes,expenses,debts}.py`):**
1. En `_target_event_dates(..., today, horizon)`: agregar `month_start = today.replace(day=1)` al inicio del
   cuerpo, y cambiar **las 2** ocurrencias de `if today <= ed <= horizon:` por `if month_start <= ed <= horizon:`.
2. En `materialize_*`: tras resolver `today` (`if today is None: today = date.today()`), agregar
   `month_start = today.replace(day=1)`, y en la guarda de borrado cambiar `e.event_date >= today` por
   `e.event_date >= month_start` (se conserva el resto de la condición, incl. protección de pagos).

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/cashflow-current-month-floor
```

---

## Task 1: incomes

**Files:** `app/services/cash_flow/incomes.py`, `tests/test_cashflow_engine_incomes.py`

- [ ] **Step 1: Tests (rojo)** — agregar a `tests/test_cashflow_engine_incomes.py` (usa helpers existentes
  `_seed_income`, `_entries`, fixture `seed_uy`; imports `date`, `datetime`, `timezone`, `Decimal`,
  `CashFlowEntry`, `CashFlowPayment` ya están):

```python
def test_recurrente_incluye_mes_actual_aunque_el_dia_paso(db_session, seed_uy):
    income = _seed_income(db_session, payment_day=5)
    materialize_income(db_session, income.id, today=date(2026, 7, 9), horizon=date(2026, 12, 31))
    entries = _entries(db_session, income)
    assert entries[0].event_date == date(2026, 7, 5)  # julio incluido (hoy 9 > día 5)


def test_fixed_term_incluye_mes_actual_excluye_pasado(db_session, seed_uy):
    income = _seed_income(
        db_session, is_monthly_recurring=False, payment_day=None,
        first_income_date=date(2026, 6, 3), total_months=2,  # jun y jul
    )
    materialize_income(db_session, income.id, today=date(2026, 7, 9), horizon=date(2026, 12, 31))
    eds = [e.event_date for e in _entries(db_session, income)]
    assert date(2026, 6, 3) not in eds   # junio (mes pasado) excluido
    assert date(2026, 7, 3) in eds       # julio (mes actual) incluido aunque el día pasó


def test_entry_mes_actual_con_pago_real_sobrevive_reproject(db_session, seed_uy):
    income = _seed_income(db_session, payment_day=5)
    materialize_income(db_session, income.id, today=date(2026, 7, 9), horizon=date(2026, 12, 31))
    jul = _entries(db_session, income)[0]
    db_session.add(CashFlowPayment(cash_flow_entry_id=jul.id, amount=Decimal("45000.00")))  # real
    db_session.flush()
    income.deleted_at = datetime.now(timezone.utc)  # targets vacíos → intentaría borrar
    db_session.flush()
    materialize_income(db_session, income.id, today=date(2026, 7, 9), horizon=date(2026, 12, 31))
    assert db_session.get(CashFlowEntry, jul.id) is not None  # protegida por pago real
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_engine_incomes.py -q
```

Expected: fallan los dos primeros (julio se omite hoy).

- [ ] **Step 3: Editar `app/services/cash_flow/incomes.py`.** En `_target_event_dates`, agregar
  `month_start = today.replace(day=1)` como primera línea tras el docstring:

```python
def _target_event_dates(income: Income, today: date, horizon: date) -> list[date]:
    """event_date de cada entry que el income debería tener. Vacío si está borrado."""
    month_start = today.replace(day=1)
    if income.deleted_at is not None:
        return []
```

Cambiar las 2 ocurrencias `if today <= ed <= horizon:` → `if month_start <= ed <= horizon:`.

En `materialize_income`, tras `today = date.today()` (dentro del `if today is None:`), agregar después del
bloque:

```python
    if today is None:
        today = date.today()
    month_start = today.replace(day=1)
```

Y en la guarda de borrado, cambiar:

```python
            if e.event_date is not None and e.event_date >= today and e.id not in paid_ids:
```

por:

```python
            if e.event_date is not None and e.event_date >= month_start and e.id not in paid_ids:
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_engine_incomes.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/incomes.py tests/test_cashflow_engine_incomes.py && git commit -m "feat: incomes materializa desde el primer día del mes actual"
```

---

## Task 2: expenses

**Files:** `app/services/cash_flow/expenses.py`, `tests/test_cashflow_expenses.py`

- [ ] **Step 1: Tests (rojo)** — agregar a `tests/test_cashflow_expenses.py` (usa fixture `user` y helper
  `_gasto`; imports `date`, `select`, `CashFlowEntry` ya están):

```python
def _entries_gasto(db_session, gasto_id):
    return list(db_session.execute(
        select(CashFlowEntry)
        .where(CashFlowEntry.source_type == "gasto", CashFlowEntry.source_id == gasto_id)
        .order_by(CashFlowEntry.event_date)
    ).scalars())


def test_gasto_recurrente_incluye_mes_actual(db_session, user):
    g = _gasto(db_session, user, due_day=10)
    materialize_expense(db_session, g.id, today=date(2026, 6, 20), horizon=date(2026, 12, 31))
    entries = _entries_gasto(db_session, g.id)
    assert entries[0].event_date == date(2026, 6, 10)  # junio incluido (hoy 20 > día 10)


def test_gasto_unico_mes_actual_aunque_paso(db_session, user):
    g = _gasto(db_session, user, is_monthly_recurring=False, due_day=None, first_due_date=date(2026, 6, 3))
    materialize_expense(db_session, g.id, today=date(2026, 6, 20), horizon=date(2026, 12, 31))
    eds = [e.event_date for e in _entries_gasto(db_session, g.id)]
    assert date(2026, 6, 3) in eds
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_expenses.py -q
```

- [ ] **Step 3: Editar `app/services/cash_flow/expenses.py`** con el mismo patrón:
  `month_start = today.replace(day=1)` al inicio de `_target_event_dates`; las 2 `if today <= ed <= horizon:` →
  `if month_start <= ed <= horizon:`; en `materialize_expense` agregar `month_start = today.replace(day=1)`
  tras resolver `today`; y la guarda de borrado:

```python
            if e.event_date is not None and e.event_date >= today:
```

por:

```python
            if e.event_date is not None and e.event_date >= month_start:
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_expenses.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/expenses.py tests/test_cashflow_expenses.py && git commit -m "feat: expenses materializa desde el primer día del mes actual"
```

---

## Task 3: debts

**Files:** `app/services/cash_flow/debts.py`, `tests/test_cashflow_debts.py`

- [ ] **Step 1: Tests (rojo)** — agregar a `tests/test_cashflow_debts.py` (usa fixture `user` y helper
  `_deuda`; imports `date`, `select`, `CashFlowEntry`, `Decimal` ya están):

```python
def _entries_deuda(db_session, deuda_id):
    return list(db_session.execute(
        select(CashFlowEntry)
        .where(CashFlowEntry.source_type == "deuda", CashFlowEntry.source_id == deuda_id)
        .order_by(CashFlowEntry.event_date)
    ).scalars())


def test_deuda_cuota_mes_actual_aunque_el_dia_paso(db_session, user):
    d = _deuda(db_session, user, first_due_date=date(2026, 6, 1), due_day=10, total_installments=12)
    materialize_debt(db_session, d.id, today=date(2026, 6, 20), horizon=date(2026, 12, 31))
    eds = [e.event_date for e in _entries_deuda(db_session, d.id)]
    assert date(2026, 6, 10) in eds  # cuota de junio incluida (hoy 20 > día 10)
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_debts.py -q
```

- [ ] **Step 3: Editar `app/services/cash_flow/debts.py`** con el mismo patrón:
  `month_start = today.replace(day=1)` al inicio de `_target_event_dates`; las 2 `if today <= ed <= horizon:` →
  `if month_start <= ed <= horizon:`; en `materialize_debt` agregar `month_start = today.replace(day=1)` tras
  resolver `today`; y la guarda de borrado `e.event_date >= today` → `e.event_date >= month_start`.

> La guarda de debts conserva su protección de pago real (raise si la fila a borrar tiene pago real); solo
> cambia el piso de fecha.

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cashflow_debts.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow/debts.py tests/test_cashflow_debts.py && git commit -m "feat: debts materializa desde el primer día del mes actual"
```

---

## Task 4: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde. **Ojo regresiones:** algún test existente puede asumir el piso "hoy" (p.ej. esperar que
el mes actual se omita cuando el día ya pasó). Si alguno falla por el nuevo piso, **corregir el test a la nueva
semántica** (el mes actual ahora se incluye) — no revertir el motor.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/cashflow-current-month-floor` a `main` (1 commit). Push **manual**. (No tocar
  Notion.)

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** los 3 motores, target (2 spots c/u) + borrado de stale (1 spot c/u) a `month_start`;
  protección de pagos intacta; tests de mes-actual + pasado-excluido + (incomes) pago-real-sobrevive. ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. ✓
- **Consistencia:** `month_start = today.replace(day=1)` definido tanto en `_target_event_dates` como en
  `materialize_*` (scopes separados); el patrón es idéntico en los 3 archivos. La guarda de borrado conserva el
  resto de su condición (paid_ids en incomes, raise-on-paid en debts). ✓
- **Sin Notion:** el cierre no incluye paso de sincronización (Notion deprecado como guía). ✓

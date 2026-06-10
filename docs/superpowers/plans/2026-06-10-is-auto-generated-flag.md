# `is_auto_generated` en `plan_movements` y `cash_flow_payments` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Agregar la columna boolean `is_auto_generated` (NOT NULL, default `false`) a `plan_movements` y
`cash_flow_payments`, y exponerla **read-only** en los schemas de salida.

**Architecture:** Columna en ambos modelos con `server_default="false"` (patrón `currency.is_legal_tender`);
migración Alembic autogenerada; campo read-only en `PlanMovementOut`, `PaymentOut` y `PaymentListItem`. No se
acepta como input en ningún Create/Update. La lógica que la consumirá (PlanningEngine) queda fuera.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-is-auto-generated-flag-design.md`

**Branch:** `feat/is-auto-generated-flag`. Squash-merge al final. **Sin Notion. Sin web.**

**Higiene:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q` (sin pipes ni
`2>&1`). Migración: `alembic revision --autogenerate` → revisar → `alembic upgrade head`. Git planos. No push.

**Nota sobre tests vs migración:** la suite arma las tablas con `create_all` desde los modelos (no corre
migraciones), así que el cambio en el **modelo** es lo que pone los tests en verde. La **migración** es aparte,
para la base de dev/prod, y se verifica con `alembic upgrade head` sobre `margin`.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/is-auto-generated-flag
```

---

## Task 1: Columna en los modelos (TDD)

**Files:**
- Modify: `app/models/plan_movement.py`
- Modify: `app/models/cash_flow_payment.py`
- Test: `tests/test_plan_movements.py`, `tests/test_cash_flow_payments_create.py`

- [ ] **Step 1: Test rojo — default false en `plan_movements`.** Agregar al final de
  `tests/test_plan_movements.py`:

```python
def test_create_movement_defaults_auto_generated_false(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    movement = client.post(f"/plans/{plan_id}/movements", json=_ingreso(income_duration_months=None), headers=headers).json()
    pm = db_session.get(PlanMovement, uuid.UUID(movement["id"]))
    assert pm.is_auto_generated is False
```

  (Este archivo ya importa `uuid` y `PlanMovement` no está importado — agregar el import al tope:
  `from app.models.plan_movement import PlanMovement`.)

- [ ] **Step 2: Test rojo — persiste true en `plan_movements`.** Agregar a `tests/test_plan_movements.py`:

```python
def test_plan_movement_auto_generated_persists_true(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    pm = PlanMovement(
        plan_id=uuid.UUID(plan_id), kind="ingreso", currency_id=1,
        principal_amount=Decimal("1000.00"), start_date=date(2026, 7, 1),
        rates_add_vat=False, is_auto_generated=True,
    )
    db_session.add(pm)
    db_session.commit()
    db_session.refresh(pm)
    assert pm.is_auto_generated is True
```

  (Agregar al tope los imports que falten: `from datetime import date` y `from decimal import Decimal`.)

- [ ] **Step 3: Test rojo — default false en `cash_flow_payments`.** Agregar a
  `tests/test_cash_flow_payments_create.py`:

```python
def test_create_payment_defaults_auto_generated_false(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    r = client.post(f"/cash-flow-entries/{entry.id}/payments", json={"amount": "4500.00"}, headers=headers)
    assert r.status_code == 201
    from app.models.cash_flow_payment import CashFlowPayment
    pay = db_session.get(CashFlowPayment, uuid.UUID(r.json()["id"]))
    assert pay.is_auto_generated is False
```

- [ ] **Step 4: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plan_movements.py::test_create_movement_defaults_auto_generated_false tests/test_plan_movements.py::test_plan_movement_auto_generated_persists_true tests/test_cash_flow_payments_create.py::test_create_payment_defaults_auto_generated_false -q
```

Expected: FALLA (`AttributeError`/`TypeError`: `is_auto_generated` no existe en el modelo).

- [ ] **Step 5: Agregar la columna a `plan_movements`.** En `app/models/plan_movement.py`, después de
  `rates_add_vat` (línea 30):

```python
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```

  (`Boolean` ya está importado en ese archivo.)

- [ ] **Step 6: Agregar la columna a `cash_flow_payments`.** En `app/models/cash_flow_payment.py`, después de
  `planned_date` (línea 22), y agregar `Boolean` al import de `sqlalchemy` (la línea 5 hoy importa
  `Date, DateTime, ForeignKey, Numeric, String, func` — agregar `Boolean`):

```python
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```

- [ ] **Step 7: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plan_movements.py::test_create_movement_defaults_auto_generated_false tests/test_plan_movements.py::test_plan_movement_auto_generated_persists_true tests/test_cash_flow_payments_create.py::test_create_payment_defaults_auto_generated_false -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/plan_movement.py app/models/cash_flow_payment.py tests/test_plan_movements.py tests/test_cash_flow_payments_create.py && git commit -m "feat: columna is_auto_generated en plan_movements y cash_flow_payments"
```

---

## Task 2: Migración Alembic

**Files:**
- Create: `alembic/versions/<rev>_is_auto_generated.py` (autogenerada)

- [ ] **Step 1: Generar la migración**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "is_auto_generated en plan_movements y cash_flow_payments"
```

- [ ] **Step 2: Revisar la migración.** Abrir el archivo generado en `alembic/versions/`. Verificar que el
  `upgrade()` agregue la columna a **ambas** tablas con server default `false`, p.ej.:

```python
def upgrade() -> None:
    op.add_column("plan_movements", sa.Column("is_auto_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("cash_flow_payments", sa.Column("is_auto_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("cash_flow_payments", "is_auto_generated")
    op.drop_column("plan_movements", "is_auto_generated")
```

  Si el autogenerate omitió una tabla o el `server_default`, editarlo a mano para que quede así. (El
  `server_default` rellena las filas preexistentes en dev con `false`.)

- [ ] **Step 3: Aplicar a la base de dev**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic upgrade head
```

Expected: aplica sin error.

- [ ] **Step 4: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add alembic/versions && git commit -m "feat: migración is_auto_generated en plan_movements y cash_flow_payments"
```

---

## Task 3: Exponer en los schemas Out (read-only) (TDD)

**Files:**
- Modify: `app/schemas/plan_movement.py`
- Modify: `app/schemas/cash_flow_payment.py`
- Test: `tests/test_plan_movements.py`, `tests/test_cash_flow_payments_create.py`,
  `tests/test_cash_flow_payments_list.py`

- [ ] **Step 1: Test rojo — `PlanMovementOut` expone el flag y Create lo ignora.** Agregar a
  `tests/test_plan_movements.py`:

```python
def test_movement_out_exposes_auto_generated_and_create_ignores_input(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    body = _ingreso(income_duration_months=None)
    body["is_auto_generated"] = True  # intento de setearlo: debe ignorarse
    movement = client.post(f"/plans/{plan_id}/movements", json=body, headers=headers).json()
    assert movement["is_auto_generated"] is False
```

- [ ] **Step 2: Test rojo — `PaymentOut` expone el flag.** Agregar a
  `tests/test_cash_flow_payments_create.py`:

```python
def test_payment_out_exposes_auto_generated_and_create_ignores_input(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    r = client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "4500.00", "is_auto_generated": True},  # debe ignorarse
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["is_auto_generated"] is False
```

- [ ] **Step 3: Test rojo — `PaymentListItem` expone el flag.** Agregar a
  `tests/test_cash_flow_payments_list.py` (este archivo ya usa `_make_entry`, `_make_plan`, `_headers`,
  `_last_user` — reusar el mismo estilo que los tests existentes del archivo):

```python
def test_list_item_exposes_auto_generated(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    entry = _make_entry(db_session, user)
    plan = _make_plan(db_session, user)
    client.post(
        f"/cash-flow-entries/{entry.id}/payments",
        json={"amount": "5000.00", "plan_id": str(plan.id), "planned_date": "2026-07-15"},
        headers=headers,
    )
    rows = client.get(f"/cash-flow-entries/{entry.id}/payments?plan_id={plan.id}", headers=headers).json()
    assert all(r["is_auto_generated"] is False for r in rows)
```

  (Verificar que los helpers `_make_plan` y `_make_entry` existan en este archivo; si no, importarlos o
  replicarlos como en `tests/test_cash_flow_payments_create.py`.)

- [ ] **Step 4: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plan_movements.py::test_movement_out_exposes_auto_generated_and_create_ignores_input tests/test_cash_flow_payments_create.py::test_payment_out_exposes_auto_generated_and_create_ignores_input tests/test_cash_flow_payments_list.py::test_list_item_exposes_auto_generated -q
```

Expected: FALLA (`KeyError`/`AssertionError`: el campo `is_auto_generated` no está en la respuesta).

- [ ] **Step 5: Exponer en `PlanMovementOut`.** En `app/schemas/plan_movement.py`, en la clase
  `PlanMovementOut` agregar el campo después de `rates_add_vat: bool` (línea 54):

```python
    is_auto_generated: bool
```

  y en `from_model` (después de `rates_add_vat=m.rates_add_vat,`):

```python
            is_auto_generated=m.is_auto_generated,
```

- [ ] **Step 6: Exponer en `PaymentOut` y `PaymentListItem`.** En `app/schemas/cash_flow_payment.py`:

  En `PaymentOut` agregar el campo después de `created_at: datetime`:

```python
    is_auto_generated: bool
```

  y en su `from_model` (después de `created_at=p.created_at,`):

```python
            is_auto_generated=p.is_auto_generated,
```

  En `PaymentListItem` agregar el campo después de `created_at: datetime`:

```python
    is_auto_generated: bool
```

  y en su `from_model` (después de `created_at=p.created_at,`):

```python
            is_auto_generated=p.is_auto_generated,
```

- [ ] **Step 7: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_plan_movements.py::test_movement_out_exposes_auto_generated_and_create_ignores_input tests/test_cash_flow_payments_create.py::test_payment_out_exposes_auto_generated_and_create_ignores_input tests/test_cash_flow_payments_list.py::test_list_item_exposes_auto_generated -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/plan_movement.py app/schemas/cash_flow_payment.py tests/test_plan_movements.py tests/test_cash_flow_payments_create.py tests/test_cash_flow_payments_list.py && git commit -m "feat: exponer is_auto_generated read-only en PlanMovementOut, PaymentOut y PaymentListItem"
```

---

## Task 4: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch. **squash-merge** a
  `main` (1 commit). Push **manual**. Sin Notion.

---

## Self-Review

- **Cobertura del spec:** §2 columna en modelos (Task 1, Steps 5-6); §3 migración (Task 2); §4 schemas Out
  read-only + Create/Update sin cambios (Task 3); §5 tests de default false / persiste true / exposición /
  Create ignora input (Tasks 1 y 3). ✓
- **Placeholder scan:** sin TBD/TODO; todo el código de tests y modelos está explícito; la migración muestra el
  `upgrade`/`downgrade` esperado. ✓
- **Consistencia de tipos:** `is_auto_generated: Mapped[bool]` (modelo) ↔ `is_auto_generated: bool` (schemas) ↔
  `is_auto_generated=...` (from_model). Mismo nombre en ambas tablas y los tres OUT. `server_default="false"`
  consistente con el patrón del repo. ✓
- **Read-only:** Create/Update no se tocan; los tests verifican que un payload con `is_auto_generated: true` se
  ignora (queda `False`). ✓

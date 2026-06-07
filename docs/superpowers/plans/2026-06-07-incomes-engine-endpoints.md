# Slice 3 — Endpoints de ingresos con el motor + borrado híbrido — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que crear/editar/reactivar un ingreso materialice sus `cash_flow_entries` (motor en la misma transacción), y que borrarlo aplique el híbrido hard/soft real.

**Architecture:** Todo el cambio vive en `app/services/income_service.py`. `create_income`/`update_income`/`reactivate_income` hacen `flush → materialize_income → commit`. `delete_income` se reescribe: cuenta pagos reales y decide hard-delete (borra todas las entries + la fila) o soft-delete (borra solo entries sin pago real + setea `deleted_at`). El router y los schemas no cambian.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest. Python 3.13 (`backend/.venv`). Tests con `create_all` (sin migración).

**Spec:** `docs/superpowers/specs/2026-06-07-incomes-engine-endpoints-design.md`.

**Git:** rama `feat/incomes-engine-endpoints`, commits chicos, **squash-merge** a `main`.

---

## Estructura de archivos

```
backend/app/services/income_service.py   # cablear motor + borrado híbrido   (MODIFICAR)
backend/tests/test_incomes.py            # helpers + tests nuevos/actualizados (MODIFICAR)
```

> **Nota:** `update_income`, `create_income` y `delete_income`/`reactivate_income` ya existen. Los tests de
> validación (POST/PATCH) no se tocan. Los de delete/reactivate **cambian de semántica** (Task 2).

---

## Task 1: Cablear el motor en create + update (TDD)

**Files:**
- Modify: `backend/app/services/income_service.py`
- Modify: `backend/tests/test_incomes.py`

- [ ] **Step 1: Crear la rama**

```bash
cd /Users/tachone/proyectos/margin
git checkout -b feat/incomes-engine-endpoints
```

- [ ] **Step 2: Agregar helpers de test e imports en `backend/tests/test_incomes.py`**

En los imports del tope del archivo, agregar (junto a los `from app.models...` existentes):

```python
import uuid

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
```

(`from sqlalchemy import select` y `from decimal import Decimal` ya están importados.)

Y agregar estos dos helpers después de los helpers existentes (`_fixed_body`, etc.):

```python
def _entries_of(db_session, income_id):
    return list(
        db_session.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == uuid.UUID(income_id),
            )
        ).scalars()
    )


def _add_real_payment(db_session, income_id):
    """Imputa un pago real (plan_id NULL) a una entry del income; devuelve esa entry.id."""
    entry = (
        db_session.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == uuid.UUID(income_id),
            )
        )
        .scalars()
        .first()
    )
    db_session.add(CashFlowPayment(cash_flow_entry_id=entry.id, amount=Decimal("1000.00")))
    db_session.flush()
    return entry.id
```

- [ ] **Step 3: Escribir los tests que fallan (create/patch materializan) al final de `backend/tests/test_incomes.py`**

```python
def test_create_materializes_entries(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)

    entries = _entries_of(db_session, income["id"])
    assert len(entries) >= 1
    assert all(e.is_income is True for e in entries)
    assert all(e.source_type == "ingreso" for e in entries)
    assert all(e.amount == Decimal("45000.00") for e in entries)


def test_patch_amount_rematerializes(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)

    resp = client.patch(f"/incomes/{income['id']}", json={"amount": "50000.00"}, headers=headers)
    assert resp.status_code == 200

    entries = _entries_of(db_session, income["id"])
    assert len(entries) >= 1
    assert all(e.amount == Decimal("50000.00") for e in entries)
```

- [ ] **Step 4: Correr y verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes.py::test_create_materializes_entries tests/test_incomes.py::test_patch_amount_rematerializes -v`
Expected: FALLAN — no se materializan entries todavía (`assert len(entries) >= 1` falla con 0).

- [ ] **Step 5: Agregar el import del motor en `backend/app/services/income_service.py`**

Después de `from app.schemas.income import IncomeCreate, IncomeUpdate`, agregar:

```python
from app.services.cash_flow.incomes import materialize_income
```

- [ ] **Step 6: Cablear `create_income`**

Reemplazar el final de `create_income`:

```python
    db.add(income)
    db.commit()
    db.refresh(income)
    return income
```

por:

```python
    db.add(income)
    db.flush()
    materialize_income(db, income.id)
    db.commit()
    db.refresh(income)
    return income
```

- [ ] **Step 7: Cablear `update_income`**

Reemplazar el final de `update_income`:

```python
    if "shift_weekends" in fields:
        income.shift_weekends = payload.shift_weekends

    db.commit()
    db.refresh(income)
    return income
```

por:

```python
    if "shift_weekends" in fields:
        income.shift_weekends = payload.shift_weekends

    db.flush()
    materialize_income(db, income.id)
    db.commit()
    db.refresh(income)
    return income
```

- [ ] **Step 8: Correr los tests nuevos y verificar que pasan**

Run: `pytest tests/test_incomes.py::test_create_materializes_entries tests/test_incomes.py::test_patch_amount_rematerializes -v`
Expected: PASAN.

- [ ] **Step 9: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos (los tests de validación de POST/PATCH siguen verdes; delete/reactivate todavía con la semántica vieja — se actualizan en Task 2).

- [ ] **Step 10: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/income_service.py backend/tests/test_incomes.py
git commit -m "feat(backend): create/update de incomes ejecutan CashFlowEngine.incomes"
```

---

## Task 2: Borrado híbrido + cablear reactivate (TDD)

**Files:**
- Modify: `backend/app/services/income_service.py`
- Modify: `backend/tests/test_incomes.py`

- [ ] **Step 1: Actualizar los tests de delete/reactivate en `backend/tests/test_incomes.py`**

**(a)** Reemplazar el test existente `test_delete_soft_deletes` por estos dos (hard cuando no hay pagos, soft cuando los hay):

```python
def test_delete_hard_when_no_real_payments(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    assert len(_entries_of(db_session, income["id"])) >= 1

    resp = client.delete(f"/incomes/{income['id']}", headers=headers)
    assert resp.status_code == 204

    # sin pagos reales: hard-delete total -> income y entries desaparecen
    assert client.get("/incomes", headers=headers).json()["incomes"] == []
    assert _entries_of(db_session, income["id"]) == []
    # ya no existe: reactivate da 404
    resp = client.post(f"/incomes/{income['id']}/reactivate", headers=headers)
    assert resp.status_code == 404


def test_delete_soft_when_real_payment(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    paid_entry_id = _add_real_payment(db_session, income["id"])

    resp = client.delete(f"/incomes/{income['id']}", headers=headers)
    assert resp.status_code == 204

    # con pago real: soft-delete -> la entry con pago sobrevive
    assert db_session.get(CashFlowEntry, paid_entry_id) is not None
    # el income queda en la lista con is_deleted=True
    listed = client.get("/incomes", headers=headers).json()["incomes"]
    assert len(listed) == 1
    assert listed[0]["id"] == income["id"]
    assert listed[0]["is_deleted"] is True
```

**(b)** Reemplazar el cuerpo del test existente `test_reactivate_revives` (ahora necesita un pago real para que el borrado sea soft y el income siga existiendo):

```python
def test_reactivate_revives(client, db_session, seed_uy):
    _seed_refs(db_session)
    headers = _auth(client)
    income = _create_recurring(client, headers)
    _add_real_payment(db_session, income["id"])  # para que el delete sea soft
    client.delete(f"/incomes/{income['id']}", headers=headers)

    resp = client.post(f"/incomes/{income['id']}/reactivate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_deleted"] is False
    # re-materializa: vuelve a tener entries
    assert len(_entries_of(db_session, income["id"])) >= 1
```

(Los demás tests de delete/reactivate — `test_delete_twice_not_found`, `test_delete_other_users_income_not_found`, `test_delete_missing_not_found`, `test_delete_requires_auth`, `test_reactivate_not_deleted_conflict`, `test_reactivate_other_users_income_not_found`, `test_reactivate_missing_not_found`, `test_reactivate_requires_auth` — siguen válidos sin cambios: el hard-delete deja el income inexistente igual que antes lo dejaba "no encontrable".)

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_incomes.py::test_delete_hard_when_no_real_payments tests/test_incomes.py::test_delete_soft_when_real_payment tests/test_incomes.py::test_reactivate_revives -v`
Expected: FALLAN — el `delete_income` provisorio hace soft incondicional (no hard, no borra entries) y `reactivate` no re-materializa.

- [ ] **Step 3: Reescribir `delete_income` y cablear `reactivate_income` en `backend/app/services/income_service.py`**

Ampliar el import de SQLAlchemy y agregar los modelos de flujo de caja. Reemplazar:

```python
from sqlalchemy import select
```

por:

```python
from sqlalchemy import delete, func, select
```

y agregar, junto a los demás `from app.models...`:

```python
from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
```

Reemplazar la función `delete_income` completa (la versión provisoria) por:

```python
def delete_income(db: Session, user: User, income_id: uuid.UUID) -> None:
    """Borrado híbrido: hard-delete si el income no tiene pagos reales, soft-delete si los tiene.
    No invoca al motor; orquesta el borrado de las cash_flow_entries con SQL directo."""
    income = db.execute(
        select(Income).where(
            Income.id == income_id,
            Income.user_id == user.id,
            Income.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if income is None:
        raise AppError(ErrorCode.not_found)

    real_payments = db.execute(
        select(func.count())
        .select_from(CashFlowPayment)
        .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
        .where(
            CashFlowEntry.source_type == "ingreso",
            CashFlowEntry.source_id == income.id,
            CashFlowPayment.plan_id.is_(None),
        )
    ).scalar_one()

    if real_payments == 0:
        # hard-delete total: todas las entries (sus planificados caen por cascade) + la fila
        db.execute(
            delete(CashFlowEntry).where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == income.id,
            )
        )
        db.delete(income)
    else:
        # soft-delete: borrar solo las entries del income SIN pago real; las con pago sobreviven
        entries_with_real_payment = (
            select(CashFlowPayment.cash_flow_entry_id)
            .join(CashFlowEntry, CashFlowPayment.cash_flow_entry_id == CashFlowEntry.id)
            .where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == income.id,
                CashFlowPayment.plan_id.is_(None),
            )
        )
        db.execute(
            delete(CashFlowEntry).where(
                CashFlowEntry.source_type == "ingreso",
                CashFlowEntry.source_id == income.id,
                CashFlowEntry.id.not_in(entries_with_real_payment),
            )
        )
        income.deleted_at = datetime.now(timezone.utc)

    db.commit()
```

Y cablear el motor en `reactivate_income`: reemplazar su final:

```python
    income.deleted_at = None
    db.commit()
    db.refresh(income)
    return income
```

por:

```python
    income.deleted_at = None
    db.flush()
    materialize_income(db, income.id)
    db.commit()
    db.refresh(income)
    return income
```

- [ ] **Step 4: Correr los tests de delete/reactivate y verificar que pasan**

Run: `pytest tests/test_incomes.py -k "delete or reactivate" -v`
Expected: PASAN todos (los nuevos y los que quedaron sin cambios).

- [ ] **Step 5: Regresión de la suite completa**

Run: `pytest -q`
Expected: pasan todos.

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services/income_service.py backend/tests/test_incomes.py
git commit -m "feat(backend): borrado híbrido de incomes + reactivate re-materializa"
```

---

## Notas de cierre

- Al terminar: crear/editar/reactivar un ingreso materializa su línea de tiempo; borrarlo aplica hard/soft real. El contrato de los endpoints no cambió. Cierra la tanda ingresos→flujo de caja.
- **Cierre:** squash-merge de `feat/incomes-engine-endpoints` → un commit `feat: incomes ejecutan el motor + borrado híbrido` en `main`.

## Self-review (writing-plans)

- **Cobertura del spec:** cablear motor en create/update/reactivate con `flush → materialize → commit` (§2) — Task 1 Steps 6-7 + Task 2 Step 3 (reactivate) ✓; borrado híbrido hard/soft con conteo de pagos reales y subquery acotado al income (§3) — Task 2 Step 3 ✓; contrato sin cambios (router/schemas intactos, sin error codes nuevos) — solo se toca `income_service.py` ✓; tests de create/patch/reactivate materializan + hard/soft delete (§5) — Task 1 Step 3 + Task 2 Step 1 ✓; testabilidad sin tocar la firma (income recurrente con fechas holgadas, se verifica count/existencia) — `_entries_of` con `>= 1` ✓.
- **Placeholders:** ninguno; código completo en cada step (imports, funciones, tests).
- **Consistencia de tipos:** `materialize_income(db, income.id)` igual que en el slice 2; `delete_income(db, user, income_id)` mantiene la firma actual (router no cambia); `CashFlowEntry`/`CashFlowPayment` con los nombres de columna reales (`source_type`, `source_id`, `cash_flow_entry_id`, `plan_id`); `_entries_of`/`_add_real_payment` usan `uuid.UUID(income["id"])` porque el id viene como string del JSON. Los tests que no cambian se listan explícitamente para no romperlos.
```

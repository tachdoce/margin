# DELETE /plans/{id}/planning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Endpoint `DELETE /plans/{plan_id}/planning` que borra los `cash_flow_payments` auto-generados de un plan sin recalcular, dejando intactos los pagos manuales y reales.

**Architecture:** Se extrae el borrado (hoy inline en `run_planning`) a dos helpers reusables — `_require_plan` (validación + 404) y `_delete_auto_payments` (el DELETE, sin commit) — y se agrega `clear_planning` que valida, borra y commitea. El router suma el verbo `DELETE` sobre el mismo path del `POST` existente, delegando en el servicio.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Postgres, pytest. Spec: `docs/superpowers/specs/2026-06-12-clear-planning-design.md`.

**Convenciones:** servicios lanzan `AppError`, nunca `HTTPException`; correr desde `backend/` con `.venv/bin/pytest`; no pipear la salida de pytest por `tail`/`head`; TDD (test que falla primero); commits en español. Rama: `feat/clear-planning` (ya existe, tiene el spec).

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `backend/app/services/planning/engine.py` (modificar) | `_require_plan`, `_delete_auto_payments`, `clear_planning`; refactor de `run_planning` para reusarlos |
| `backend/app/services/planning/__init__.py` (modificar) | exportar `clear_planning` además de `run_planning` |
| `backend/app/routers/plans.py` (modificar) | endpoint `DELETE /plans/{plan_id}/planning` (delega, 204) |
| `backend/tests/test_planning.py` (modificar) | tests del servicio + endpoint |

---

### Task 1: Refactor — extraer `_require_plan` y `_delete_auto_payments` de `run_planning`

Refactor sin cambio de comportamiento: la suite existente de `run_planning` es la red de seguridad. No se agregan tests en esta task; se verifica que los existentes siguen verdes.

**Files:**
- Modify: `backend/app/services/planning/engine.py`

- [ ] **Step 1: Ver el bloque actual**

El inicio de `run_planning` hoy es:

```python
def run_planning(db: Session, user: User, plan_id: uuid.UUID, *, today: date | None = None) -> None:
    today = today or date.today()
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)

    db.execute(
        delete(CashFlowPayment).where(
            CashFlowPayment.plan_id == plan.id,
            CashFlowPayment.is_auto_generated.is_(True),
        )
    )

    month_start = today.replace(day=1)
```

- [ ] **Step 2: Extraer los helpers y reusarlos**

Reemplazar ese bloque (desde la línea `def run_planning(...)` hasta `    month_start = today.replace(day=1)` inclusive) por:

```python
def _require_plan(db: Session, user: User, plan_id: uuid.UUID) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return plan


def _delete_auto_payments(db: Session, plan_id: uuid.UUID) -> None:
    """Borra los pagos auto-generados del plan. Sin commit (lo maneja quien llama)."""
    db.execute(
        delete(CashFlowPayment).where(
            CashFlowPayment.plan_id == plan_id,
            CashFlowPayment.is_auto_generated.is_(True),
        )
    )


def run_planning(db: Session, user: User, plan_id: uuid.UUID, *, today: date | None = None) -> None:
    today = today or date.today()
    plan = _require_plan(db, user, plan_id)

    _delete_auto_payments(db, plan.id)

    month_start = today.replace(day=1)
```

(`delete` y `CashFlowPayment` ya están importados en el archivo; no agregar imports.)

- [ ] **Step 3: Verificar que la suite de planning sigue verde**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -v`
Expected: PASS los 26 tests existentes (refactor sin cambio de comportamiento).

- [ ] **Step 4: Commit**

```bash
git add app/services/planning/engine.py
git commit -m "refactor(planning): extrae _require_plan y _delete_auto_payments"
```

---

### Task 2: `clear_planning` (servicio) + export

**Files:**
- Modify: `backend/app/services/planning/engine.py`
- Modify: `backend/app/services/planning/__init__.py`
- Test: `backend/tests/test_planning.py`

- [ ] **Step 1: Escribir los tests que fallan**

Primero, cambiar el import al principio de `backend/tests/test_planning.py`:

```python
from app.services.planning import run_planning
```

por:

```python
from app.services.planning import clear_planning, run_planning
```

Luego agregar al final de `backend/tests/test_planning.py` (usa los helpers ya definidos: `_user`, `_plan`, `_cash`, `_need`, `_entry`, `_pay`, `_autos`):

```python
# --- clear_planning: borra solo lo auto-generado ---

def test_clear_borra_solo_autos_y_deja_manuales(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    _cash(db_session, user, "0")
    _need(db_session, user, "0")
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="2000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="300.00")
    manual = _pay(db_session, card, "50.00", plan_id=plan.id, planned_date=date(2026, 6, 22))
    run_planning(db_session, user, plan.id, today=TODAY)
    assert _autos(db_session, plan)  # hay al menos uno

    clear_planning(db_session, user, plan.id)

    assert _autos(db_session, plan) == []  # autos borrados
    assert db_session.get(CashFlowPayment, manual.id) is not None  # el manual sobrevive


def test_clear_idempotente_sin_autos(db_session, seed_uy_currency):
    user = _user(db_session)
    plan = _plan(db_session, user)
    clear_planning(db_session, user, plan.id)  # no hay nada que borrar -> no rompe
    assert _autos(db_session, plan) == []


def test_clear_plan_inexistente(db_session, seed_uy_currency):
    user = _user(db_session)
    with pytest.raises(AppError) as exc:
        clear_planning(db_session, user, uuid.uuid4())
    assert exc.value.code == ErrorCode.not_found


def test_clear_plan_de_otro_usuario(db_session, seed_uy_currency):
    user = _user(db_session)
    other = _user(db_session)
    plan = _plan(db_session, other)
    with pytest.raises(AppError) as exc:
        clear_planning(db_session, user, plan.id)
    assert exc.value.code == ErrorCode.not_found


def test_clear_no_toca_autos_de_otro_plan(db_session, seed_uy_currency):
    user = _user(db_session)
    plan_a = _plan(db_session, user)
    plan_b = _plan(db_session, user)
    card = _entry(db_session, user, event_date=date(2026, 6, 22), amount="2000.00",
                  source_type="tarjeta_credito", fin="50.00", over="60.00", minimum="300.00")
    auto_b = _pay(db_session, card, "300.00", plan_id=plan_b.id, planned_date=date(2026, 6, 22), auto=True)
    clear_planning(db_session, user, plan_a.id)
    assert db_session.get(CashFlowPayment, auto_b.id) is not None  # el auto del otro plan sobrevive
```

- [ ] **Step 2: Verificar que fallan**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -k clear -v`
Expected: ERROR de colección — `ImportError: cannot import name 'clear_planning'`.

- [ ] **Step 3: Implementar `clear_planning`**

En `backend/app/services/planning/engine.py`, agregar `clear_planning` entre `_delete_auto_payments` y `run_planning`:

```python
def clear_planning(db: Session, user: User, plan_id: uuid.UUID) -> None:
    """Borra los pagos auto-generados del plan sin recalcular. Los manuales no se tocan."""
    plan = _require_plan(db, user, plan_id)
    _delete_auto_payments(db, plan.id)
    db.commit()
```

En `backend/app/services/planning/__init__.py`, reemplazar el contenido completo por:

```python
from app.services.planning.engine import clear_planning, run_planning

__all__ = ["clear_planning", "run_planning"]
```

- [ ] **Step 4: Verificar que pasan**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py -k clear -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/planning/engine.py app/services/planning/__init__.py tests/test_planning.py
git commit -m "feat(planning): clear_planning borra los pagos auto sin recalcular"
```

---

### Task 3: Endpoint `DELETE /plans/{plan_id}/planning`

**Files:**
- Modify: `backend/app/routers/plans.py`
- Test: `backend/tests/test_planning.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `backend/tests/test_planning.py`:

```python
def test_endpoint_delete_204_and_404(client, db_session, seed_uy_currency):
    token = client.post("/auth/register", json={"email": "clr@x.com", "password": "12345678"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    user = db_session.execute(select(User)).scalars().all()[-1]
    plan = _plan(db_session, user)
    assert client.delete(f"/plans/{plan.id}/planning", headers=headers).status_code == 204
    assert client.delete(f"/plans/{uuid.uuid4()}/planning", headers=headers).status_code == 404
```

- [ ] **Step 2: Verificar que falla**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py::test_endpoint_delete_204_and_404 -v`
Expected: FAIL — el `DELETE` devuelve 405 (Method Not Allowed) porque el endpoint no existe.

- [ ] **Step 3: Agregar el endpoint**

En `backend/app/routers/plans.py`, agregar después del endpoint `run_planning` (el `POST .../planning`):

```python
@router.delete("/plans/{plan_id}/planning", status_code=status.HTTP_204_NO_CONTENT)
def clear_planning(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    planning.clear_planning(db, user, plan_id)
```

(`planning`, `status`, `Depends`, `get_current_user`, `get_db`, `User`, `uuid` ya están importados en el archivo.)

- [ ] **Step 4: Verificar que pasa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest tests/test_planning.py::test_endpoint_delete_204_and_404 -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/plans.py tests/test_planning.py
git commit -m "feat: DELETE /plans/{id}/planning borra lo auto-calculado"
```

---

### Task 4: Verificación final

- [ ] **Step 1: Suite completa**

Run: `cd /Users/tachone/proyectos/margin/backend && .venv/bin/pytest -q`
Expected: todo PASS (los 6 nuevos + los existentes), ningún test roto por el refactor de Task 1.

- [ ] **Step 2: Terminar la rama**

Usar superpowers:finishing-a-development-branch (squash-merge a `main`, push manual — convención del repo).

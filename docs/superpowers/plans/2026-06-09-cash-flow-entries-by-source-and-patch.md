# by-source + PATCH cash-flow-entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `GET /cash-flow-entries/by-source?source_id=` (lista las entries editables de una fuente, mes actual
en adelante) y `PATCH /cash-flow-entries/{entry_id}` (edita el `amount` proyectado de una entry).

**Architecture:** Router thin → service que extiende `cash_flow_entry_service` con la constante
`EDITABLE_ENTRY_SOURCE_TYPES` y dos funciones. Edición blanda (no corre el motor). Schema liviano compartido.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-09-cash-flow-entries-by-source-and-patch-design.md`

**Branch:** `feat/cash-flow-entries-edit` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

**Patrones del repo (verificados):**
- `amount_invalid` y `not_found` YA existen en `errors.py` (reusar). 3 codes nuevos.
- `ObligationType.obligation_kind` ∈ `{gasto, deuda, deuda_abierta}` (= los `source_type` de obligaciones).
  `Obligation` tiene FK `obligation_type_id` y `priority_level`. Tests seedean `PriorityLevel` + `ObligationType`
  directo (ver `tests/test_obligations.py`).
- `CashFlowEntry` tiene `updated_at` con `onupdate=func.now()` → se actualiza solo al cambiar `amount`.
- Service del slice anterior: `app/services/cash_flow_entry_service.py` (se extiende).
- Fixtures: `seed_uy_currency` (UY + Peso id 1). Helpers de test `_headers`/`_last_user` (ver slices previos).

---

## File Structure

| Archivo | Cambio |
|---|---|
| `app/core/errors.py` | + 3 codes |
| `app/schemas/cash_flow_entry.py` | + `SourceEntryOut`, `EntryAmountUpdate` |
| `app/services/cash_flow_entry_service.py` | + `EDITABLE_ENTRY_SOURCE_TYPES`, `list_by_source`, `update_entry_amount` |
| `app/routers/cash_flow_entries.py` | + GET by-source, PATCH |
| `tests/test_cash_flow_entries_by_source.py` | GET |
| `tests/test_patch_cash_flow_entry.py` | PATCH |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/cash-flow-entries-edit
```

---

## Task 1: Codes + schemas + service base + GET by-source

**Files:**
- Modify: `app/core/errors.py`, `app/schemas/cash_flow_entry.py`,
  `app/services/cash_flow_entry_service.py`, `app/routers/cash_flow_entries.py`
- Create: `tests/test_cash_flow_entries_by_source.py`

- [ ] **Step 1: Codes** en `app/core/errors.py` (dentro de `ErrorCode`, tras los del grupo de pagos):

```python
    source_id_required = (422, "Falta indicar la fuente.")
    source_not_editable = (422, "Este tipo de movimiento no se puede editar.")
    entry_not_editable = (409, "No se puede editar un mes ya pasado.")
```

- [ ] **Step 2: Schemas** en `app/schemas/cash_flow_entry.py` (agregar; el módulo ya existe del slice del
  GET). Agregar import de `ConfigDict`:

```python
from pydantic import BaseModel, ConfigDict
```

```python
class SourceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_date: date
    amount: Decimal
    currency_id: int
    source_type: str


class EntryAmountUpdate(BaseModel):
    amount: Decimal
```

(`date`, `Decimal`, `uuid` ya están importados en ese archivo.)

- [ ] **Step 3: Service** — agregar a `app/services/cash_flow_entry_service.py`. Imports nuevos arriba:

```python
from datetime import date

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
```

(Si alguno ya está importado, no dupliques.) Y al final del módulo:

```python
EDITABLE_ENTRY_SOURCE_TYPES = ("gasto",)


def list_by_source(db, user, source_id, *, today: date | None = None):
    if source_id is None:
        raise AppError(ErrorCode.source_id_required)
    today = today or date.today()

    kind = db.execute(
        select(ObligationType.obligation_kind)
        .join(Obligation, Obligation.obligation_type_id == ObligationType.id)
        .where(Obligation.id == source_id, Obligation.user_id == user.id)
    ).scalar_one_or_none()
    if kind is None:
        raise AppError(ErrorCode.not_found)
    if kind not in EDITABLE_ENTRY_SOURCE_TYPES:
        raise AppError(ErrorCode.source_not_editable)

    month_start = today.replace(day=1)
    stmt = (
        select(CashFlowEntry)
        .where(
            CashFlowEntry.user_id == user.id,
            CashFlowEntry.source_id == source_id,
            CashFlowEntry.source_type.in_(EDITABLE_ENTRY_SOURCE_TYPES),
            CashFlowEntry.event_date >= month_start,
        )
        .order_by(CashFlowEntry.event_date.asc())
    )
    return list(db.execute(stmt).scalars())
```

> `kind` (obligation_kind) coincide con el `source_type` de la obligación (gasto/deuda/deuda_abierta), por eso
> se compara directo contra `EDITABLE_ENTRY_SOURCE_TYPES`.

- [ ] **Step 4: Router** — agregar a `app/routers/cash_flow_entries.py`. Asegurar imports `Query`,
  `SourceEntryOut`:

```python
from fastapi import APIRouter, Depends, Query
```
```python
from app.schemas.cash_flow_entry import SourceEntryOut, TimelineOut
```
```python
@router.get("/cash-flow-entries/by-source", response_model=list[SourceEntryOut])
def list_by_source(
    source_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SourceEntryOut]:
    return svc.list_by_source(db, user, source_id)
```

- [ ] **Step 5: Tests** `tests/test_cash_flow_entries_by_source.py`:

```python
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.user import User

TODAY = date.today()
MONTH_START = TODAY.replace(day=1)
PAST = MONTH_START - timedelta(days=1)        # último día del mes anterior
FUTURE = MONTH_START + timedelta(days=45)     # ~mes siguiente


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    return db_session.execute(select(User)).scalars().all()[-1]


def _seed_types(db_session):
    db_session.merge(PriorityLevel(level=2, name="Esencial", description="x"))
    db_session.merge(ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                                    description="x", default_priority_level=2, visible=True))
    db_session.merge(ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                                    description="x", default_priority_level=2, visible=True))
    db_session.commit()


def _obligation(db_session, user, *, type_id=1):
    o = Obligation(
        user_id=user.id, obligation_type_id=type_id, priority_level=2, description="Luz",
        is_monthly_recurring=True, currency_id=1, amount=Decimal("3000.00"), shift_weekends=False,
        rates_add_vat=False, is_closed=False, review_findings="[]", is_ready=True,
    )
    db_session.add(o)
    db_session.commit()
    db_session.refresh(o)
    return o


def _entry(db_session, user, source, *, event_date, amount="3000.00", source_type="gasto"):
    e = CashFlowEntry(
        user_id=user.id, event_date=event_date, is_income=False, amount=Decimal(amount),
        currency_id=1, source_type=source_type, source_id=source.id,
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


def test_requires_source_id(client, db_session, seed_uy_currency):
    headers = _headers(client)
    assert client.get("/cash-flow-entries/by-source", headers=headers).json()["code"] == "source_id_required"


def test_source_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    assert client.get(f"/cash-flow-entries/by-source?source_id={uuid.uuid4()}", headers=headers).status_code == 404


def test_source_of_other_user(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers_a = _headers(client, email="a@b.com")
    user_a = _last_user(db_session)
    o = _obligation(db_session, user_a)
    headers_b = _headers(client, email="b@b.com")
    assert client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers_b).status_code == 404


def test_source_not_editable(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user, type_id=10)  # deuda
    r = client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers)
    assert r.json()["code"] == "source_not_editable"


def test_lists_current_and_future_excludes_past_ordered(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    _entry(db_session, user, o, event_date=PAST, amount="1.00")
    _entry(db_session, user, o, event_date=FUTURE, amount="2.00")
    _entry(db_session, user, o, event_date=MONTH_START, amount="3.00")
    rows = client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers).json()
    assert [r["amount"] for r in rows] == ["3.00", "2.00"]  # current luego future; past excluido
    assert set(rows[0].keys()) == {"id", "event_date", "amount", "currency_id", "source_type"}


def test_empty_when_no_current_or_future(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    _entry(db_session, user, o, event_date=PAST, amount="1.00")
    assert client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers).json() == []
```

> Si `Obligation`/`ObligationType`/`PriorityLevel` exigen columnas NOT NULL no provistas, completalas leyendo
> el modelo (mismo criterio que slices previos).

- [ ] **Step 6: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_entries_by_source.py -q
```

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/core/errors.py app/schemas/cash_flow_entry.py app/services/cash_flow_entry_service.py app/routers/cash_flow_entries.py tests/test_cash_flow_entries_by_source.py && git commit -m "feat: GET cash-flow-entries/by-source"
```

---

## Task 2: PATCH cash-flow-entries/{entry_id}

**Files:**
- Modify: `app/services/cash_flow_entry_service.py`, `app/routers/cash_flow_entries.py`
- Create: `tests/test_patch_cash_flow_entry.py`

- [ ] **Step 1: Service** — agregar `update_entry_amount`:

```python
def update_entry_amount(db, user, entry_id, amount, *, today: date | None = None):
    today = today or date.today()
    entry = db.get(CashFlowEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    if entry.source_type not in EDITABLE_ENTRY_SOURCE_TYPES:
        raise AppError(ErrorCode.source_not_editable)
    if entry.event_date is None or entry.event_date < today.replace(day=1):
        raise AppError(ErrorCode.entry_not_editable)
    if amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")
    entry.amount = amount
    db.flush()
    db.commit()
    db.refresh(entry)
    return entry
```

- [ ] **Step 2: Router** — agregar la ruta PATCH y el import de `EntryAmountUpdate`:

```python
from app.schemas.cash_flow_entry import EntryAmountUpdate, SourceEntryOut, TimelineOut
```
```python
@router.patch("/cash-flow-entries/{entry_id}", response_model=SourceEntryOut)
def update_entry(
    entry_id: uuid.UUID,
    payload: EntryAmountUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SourceEntryOut:
    return svc.update_entry_amount(db, user, entry_id, payload.amount)
```

- [ ] **Step 3: Tests** `tests/test_patch_cash_flow_entry.py` (reusar los helpers de Task 1):

```python
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.cash_flow_entry import CashFlowEntry
from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.user import User

TODAY = date.today()
MONTH_START = TODAY.replace(day=1)
PAST = MONTH_START - timedelta(days=1)
FUTURE = MONTH_START + timedelta(days=45)


def _headers(client, email="u@b.com"):
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _last_user(db_session):
    return db_session.execute(select(User)).scalars().all()[-1]


def _seed_types(db_session):
    db_session.merge(PriorityLevel(level=2, name="Esencial", description="x"))
    db_session.merge(ObligationType(id=1, obligation_kind="gasto", code="alquiler", name="Alquiler",
                                    description="x", default_priority_level=2, visible=True))
    db_session.commit()


def _obligation(db_session, user):
    o = Obligation(
        user_id=user.id, obligation_type_id=1, priority_level=2, description="Luz",
        is_monthly_recurring=True, currency_id=1, amount=Decimal("3000.00"), shift_weekends=False,
        rates_add_vat=False, is_closed=False, review_findings="[]", is_ready=True,
    )
    db_session.add(o)
    db_session.commit()
    db_session.refresh(o)
    return o


def _entry(db_session, user, *, source_id, event_date, amount="3000.00", source_type="gasto"):
    e = CashFlowEntry(
        user_id=user.id, event_date=event_date, is_income=False, amount=Decimal(amount),
        currency_id=1, source_type=source_type, source_id=source_id,
    )
    db_session.add(e)
    db_session.commit()
    db_session.refresh(e)
    return e


def test_patch_amount_ok(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    e = _entry(db_session, user, source_id=o.id, event_date=FUTURE, amount="3000.00")
    r = client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "6000.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["amount"] == "6000.00"
    assert set(r.json().keys()) == {"id", "event_date", "amount", "currency_id", "source_type"}


def test_patch_current_month_ok(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    e = _entry(db_session, user, source_id=o.id, event_date=MONTH_START, amount="3000.00")
    assert client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "1.00"}, headers=headers).status_code == 200


def test_patch_not_found(client, db_session, seed_uy_currency):
    headers = _headers(client)
    assert client.patch(f"/cash-flow-entries/{uuid.uuid4()}", json={"amount": "1.00"}, headers=headers).status_code == 404


def test_patch_source_not_editable(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    e = _entry(db_session, user, source_id=uuid.uuid4(), event_date=FUTURE, source_type="tarjeta_credito")
    r = client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "1.00"}, headers=headers)
    assert r.json()["code"] == "source_not_editable"


def test_patch_past_month_not_editable(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    e = _entry(db_session, user, source_id=o.id, event_date=PAST)
    r = client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "1.00"}, headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "entry_not_editable"


def test_patch_amount_invalid(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user)
    e = _entry(db_session, user, source_id=o.id, event_date=FUTURE)
    assert client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "0"}, headers=headers).json()["code"] == "amount_invalid"
    assert client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "-5"}, headers=headers).json()["code"] == "amount_invalid"
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_patch_cash_flow_entry.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py app/routers/cash_flow_entries.py tests/test_patch_cash_flow_entry.py && git commit -m "feat: PATCH cash-flow-entries/{id}"
```

---

## Task 3: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (490 previos + los nuevos).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/cash-flow-entries-edit` a `main` (1 commit). Push **manual**.

> Notion ya documenta ambos endpoints tal cual; no requiere actualización. Con este slice queda **completo el
> grupo de 7 endpoints de cash-flow-entries**.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** constante + schemas + 3 codes (Task 1), GET by-source con resolución vía
  obligations + filtro mes-actual + orden (Task 1), PATCH con las 4 validaciones en orden + edición blanda
  (Task 2). Reusa `amount_invalid`/`not_found`. ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. ✓
- **Consistencia de tipos:** `SourceEntryOut` (from_attributes, ambos endpoints) y `EntryAmountUpdate`;
  `list_by_source`/`update_entry_amount` con las firmas usadas por el router; `EDITABLE_ENTRY_SOURCE_TYPES`
  comparado contra `obligation_kind` (= source_type). ✓
- **Fechas en tests:** relativas a `date.today()` (PAST/MONTH_START/FUTURE), estables sin importar el día de
  corrida (el endpoint usa `date.today()` real; el param `today` del service queda para futuros unit-tests). ✓
- **Routing:** `GET /cash-flow-entries/by-source` literal, sin choque con `GET /cash-flow-entries` ni con
  `PATCH /cash-flow-entries/{entry_id}`. ✓
- **Riesgo conocido:** columnas NOT NULL de `Obligation` en el helper — el implementer ajusta leyendo el modelo
  si algo falla (proven en slices previos).

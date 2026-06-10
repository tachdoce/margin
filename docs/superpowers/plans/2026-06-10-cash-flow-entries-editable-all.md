# cash_flow_entries — editar cualquier grupo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Todos los `cash_flow_source_type` editables + `by-source` genérico (resuelve la fuente desde las
propias `cash_flow_entries`, no desde `obligations`).

**Architecture:** Dos cambios en `app/services/cash_flow_entry_service.py`: la tupla `EDITABLE_ENTRY_SOURCE_TYPES`
pasa a ser todos los tipos, y `list_by_source` resuelve el `source_type` mirando las entries (quita el JOIN a
obligations). Misma ruta y contrato del endpoint.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-cash-flow-entries-editable-all-design.md`

**Branch:** `feat/cash-flow-entries-editable-all` (NO trabajar en `main`). Squash-merge al final. **No Notion.**

**Higiene de comandos:** `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`.
Tests `pytest -q` (sin pipes, sin `2>&1`). Git planos. No push.

**Estado actual (verificado):**
- `app/services/cash_flow_entry_service.py`: `EDITABLE_ENTRY_SOURCE_TYPES = ("gasto",)`; `list_by_source`
  resuelve con JOIN a `Obligation`/`ObligationType` (toma `obligation_kind`); importa `Obligation`,
  `ObligationType` (solo para eso), `CashFlowEntry`, `Plan` (Plan se usa en `get_timeline`).
- `app/models/cash_flow_entry.py`: `CASH_FLOW_SOURCE_TYPES = (gasto, deuda, deuda_abierta, ingreso,
  plan_movimiento, plan_movimiento_entrada, tarjeta_credito)`.
- Tests: `tests/test_cash_flow_entries_by_source.py` (helpers `_headers`, `_last_user`, `_seed_types`,
  `_obligation`, `_entry`; constantes `MONTH_START`, `PAST`, `FUTURE`) y `tests/test_patch_cash_flow_entry.py`.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/cash-flow-entries-editable-all
```

---

## Task 1: Cambio + tests (TDD)

**Files:** `app/services/cash_flow_entry_service.py`, `tests/test_cash_flow_entries_by_source.py`,
`tests/test_patch_cash_flow_entry.py`

- [ ] **Step 1: Actualizar/agregar los tests (rojo).**

(a) En `tests/test_cash_flow_entries_by_source.py`, **reemplazar** `test_source_not_editable` por una versión
que verifica que una `deuda` ahora se lista (editable), y **agregar** un test genérico no-obligación. (Asegurar
`import uuid` y `from app.models.cash_flow_entry import CashFlowEntry` en el archivo — el helper `_entry` ya usa
`CashFlowEntry`.)

```python
def test_deuda_source_now_listed(client, db_session, seed_uy_currency):
    _seed_types(db_session)
    headers = _headers(client)
    user = _last_user(db_session)
    o = _obligation(db_session, user, type_id=10)  # deuda
    _entry(db_session, user, o, event_date=MONTH_START, amount="2.00", source_type="deuda")
    rows = client.get(f"/cash-flow-entries/by-source?source_id={o.id}", headers=headers).json()
    assert [r["amount"] for r in rows] == ["2.00"]  # deuda ahora es editable → lista


def test_by_source_generic_non_obligation(client, db_session, seed_uy_currency):
    # fuente NO-obligación (ingreso): by-source resuelve por las entries, sin tabla obligations
    import uuid as _uuid
    from decimal import Decimal as _Dec

    from app.models.cash_flow_entry import CashFlowEntry as _CFE

    headers = _headers(client)
    user = _last_user(db_session)
    source_id = _uuid.uuid4()
    db_session.add(_CFE(
        user_id=user.id, event_date=MONTH_START, is_income=True, amount=_Dec("45000.00"),
        currency_id=1, source_type="ingreso", source_id=source_id,
    ))
    db_session.commit()
    rows = client.get(f"/cash-flow-entries/by-source?source_id={source_id}", headers=headers).json()
    assert [r["source_type"] for r in rows] == ["ingreso"]
```

(b) En `tests/test_patch_cash_flow_entry.py`, **reemplazar** `test_patch_source_not_editable` por una que
verifica que `tarjeta_credito` ahora es editable:

```python
def test_patch_credit_card_now_editable(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    e = _entry(db_session, user, source_id=uuid.uuid4(), event_date=FUTURE, source_type="tarjeta_credito")
    r = client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "1.00"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["amount"] == "1.00"
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_entries_by_source.py tests/test_patch_cash_flow_entry.py -q
```

Expected: fallan los nuevos (deuda/tarjeta dan `source_not_editable`; el genérico da 404 por el JOIN a
obligations).

- [ ] **Step 3: Cambiar el servicio** `app/services/cash_flow_entry_service.py`.

(a) Imports: agregar `CASH_FLOW_SOURCE_TYPES` y **quitar** `Obligation`/`ObligationType`:

```python
from app.models.cash_flow_entry import CASH_FLOW_SOURCE_TYPES, CashFlowEntry
```
(eliminar las líneas `from app.models.obligation import Obligation` y
`from app.models.obligation_type import ObligationType`.)

(b) La tupla:

```python
EDITABLE_ENTRY_SOURCE_TYPES = CASH_FLOW_SOURCE_TYPES
```

(c) En `list_by_source`, reemplazar el bloque de resolución por obligación:

```python
    kind = db.execute(
        select(ObligationType.obligation_kind)
        .join(Obligation, Obligation.obligation_type_id == ObligationType.id)
        .where(Obligation.id == source_id, Obligation.user_id == user.id)
    ).scalar_one_or_none()
    if kind is None:
        raise AppError(ErrorCode.not_found)
    if kind not in EDITABLE_ENTRY_SOURCE_TYPES:
        raise AppError(ErrorCode.source_not_editable)
```

por la resolución vía las entries:

```python
    source_type = db.execute(
        select(CashFlowEntry.source_type)
        .where(CashFlowEntry.source_id == source_id, CashFlowEntry.user_id == user.id)
        .limit(1)
    ).scalar_one_or_none()
    if source_type is None:
        raise AppError(ErrorCode.not_found)
    if source_type not in EDITABLE_ENTRY_SOURCE_TYPES:
        raise AppError(ErrorCode.source_not_editable)
```

(El resto de `list_by_source` —`month_start`, el `select(CashFlowEntry)` con el filtro y el orden— queda igual.
`source_not_editable` y sus dos chequeos se mantienen aunque hoy sean inalcanzables.)

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_cash_flow_entries_by_source.py tests/test_patch_cash_flow_entry.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py tests/test_cash_flow_entries_by_source.py tests/test_patch_cash_flow_entry.py && git commit -m "feat: todos los cash_flow_source_type editables + by-source genérico"
```

---

## Task 2: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde. Si algún otro test asumía que un tipo no era editable, ajustarlo a la nueva semántica.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/cash-flow-entries-editable-all` a `main` (1 commit). Push **manual**. (Sin Notion.)

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** tupla = todos (`CASH_FLOW_SOURCE_TYPES`); `list_by_source` resuelve vía entries
  (quita JOIN a obligations); tests actualizados (deuda listada, genérico ingreso) y patch tarjeta editable. ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. ✓
- **Consistencia:** se importa `CASH_FLOW_SOURCE_TYPES` y se quitan `Obligation`/`ObligationType` (solo se usaban
  en `list_by_source`; `Plan` sigue usándose en `get_timeline`, no se toca). El nuevo test genérico inserta una
  entry `ingreso` directa (sin obligación) — prueba la resolución polimórfica. ✓
- **`source_not_editable`:** queda en el código (inalcanzable hoy) para cuando se pode la tupla; sin test que lo
  dispare, a propósito. ✓
- **Riesgo:** verificar que `Obligation`/`ObligationType` no se usen en otra parte del archivo antes de quitar
  los imports (en el estado actual solo los usa `list_by_source`). ✓

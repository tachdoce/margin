# Quitar tarjeta_credito de los editables — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans o
> superpowers:subagent-driven-development. Steps con checkbox (`- [ ]`).

**Goal:** `tarjeta_credito` deja de ser editable: tupla explícita de los otros 6 en
`EDITABLE_ENTRY_SOURCE_TYPES`.

**Architecture:** Un cambio en `app/services/cash_flow_entry_service.py` (la tupla) + 2 tests. El bootstrap y la
web reflejan el array solos (lo sirven/leen).

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-prune-credit-card-editable-design.md`

**Branch:** `feat/prune-credit-card-editable`. Squash-merge al final. **No Notion. Sin web.**

**Higiene:** `cd .../backend && source .venv/bin/activate && pytest -q` (sin pipes/`2>&1`). Git planos. No push.

**Estado actual (verificado):**
- `cash_flow_entry_service.py`: `from app.models.cash_flow_entry import CASH_FLOW_SOURCE_TYPES, CashFlowEntry`;
  `EDITABLE_ENTRY_SOURCE_TYPES = CASH_FLOW_SOURCE_TYPES  # todos editables (...)`.
- `tests/test_patch_cash_flow_entry.py::test_patch_credit_card_now_editable` (tarjeta → 200).
- `tests/test_cash_flow_entries_by_source.py`: helpers `_headers`, `_last_user`; imports `uuid`, `Decimal`,
  `CashFlowEntry`; constante `MONTH_START`.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/prune-credit-card-editable
```

---

## Task 1: Tests (rojo) + cambio (verde)

**Files:** `tests/test_patch_cash_flow_entry.py`, `tests/test_cash_flow_entries_by_source.py`,
`app/services/cash_flow_entry_service.py`

- [ ] **Step 1: Tests.**

(a) En `tests/test_patch_cash_flow_entry.py`, **reemplazar** `test_patch_credit_card_now_editable`:

```python
def test_patch_credit_card_not_editable(client, db_session, seed_uy_currency):
    # tarjeta_credito ya no es editable: el monto sale del resumen real
    headers = _headers(client)
    user = _last_user(db_session)
    e = _entry(db_session, user, source_id=uuid.uuid4(), event_date=FUTURE, source_type="tarjeta_credito")
    r = client.patch(f"/cash-flow-entries/{e.id}", json={"amount": "1.00"}, headers=headers)
    assert r.json()["code"] == "source_not_editable"
```

(b) En `tests/test_cash_flow_entries_by_source.py`, **agregar**:

```python
def test_by_source_credit_card_not_editable(client, db_session, seed_uy_currency):
    headers = _headers(client)
    user = _last_user(db_session)
    source_id = uuid.uuid4()
    db_session.add(CashFlowEntry(
        user_id=user.id, event_date=MONTH_START, is_income=False, amount=Decimal("1000.00"),
        currency_id=1, source_type="tarjeta_credito", source_id=source_id,
    ))
    db_session.commit()
    r = client.get(f"/cash-flow-entries/by-source?source_id={source_id}", headers=headers)
    assert r.json()["code"] == "source_not_editable"
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_patch_cash_flow_entry.py tests/test_cash_flow_entries_by_source.py -q
```

Expected: fallan los dos de tarjeta (hoy tarjeta es editable → PATCH 200 / by-source lista).

- [ ] **Step 3: Cambiar el servicio** `app/services/cash_flow_entry_service.py`.

(a) Revertir el import:

```python
from app.models.cash_flow_entry import CashFlowEntry
```
(quitar `CASH_FLOW_SOURCE_TYPES`.)

(b) La tupla:

```python
EDITABLE_ENTRY_SOURCE_TYPES = (
    "gasto",
    "deuda",
    "deuda_abierta",
    "ingreso",
    "plan_movimiento",
    "plan_movimiento_entrada",
)  # tarjeta_credito excluido: el monto sale del resumen real y el motor lo pisa
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_patch_cash_flow_entry.py tests/test_cash_flow_entries_by_source.py tests/test_bootstrap.py -q
```

(El test del bootstrap se ajusta solo: assertea `== list(EDITABLE_ENTRY_SOURCE_TYPES)`.)

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/cash_flow_entry_service.py tests/test_patch_cash_flow_entry.py tests/test_cash_flow_entries_by_source.py && git commit -m "feat: tarjeta_credito deja de ser editable"
```

---

## Task 2: Suite completa + cierre

- [ ] **Step 1: Suite completa**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch. **squash-merge** a
  `main` (1 commit). Push **manual**. Sin Notion.

---

## Self-Review

- **Cobertura del spec:** tupla explícita sin tarjeta + import revertido (Task 1); tests de tarjeta →
  `source_not_editable` en PATCH y by-source; bootstrap test se ajusta solo. ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. ✓
- **Consistencia:** los 6 tipos restantes siguen editables (tests de gasto/deuda/ingreso no cambian);
  `source_not_editable` vuelve a ser alcanzable. ✓

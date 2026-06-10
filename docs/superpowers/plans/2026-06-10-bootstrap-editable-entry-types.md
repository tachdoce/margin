# Bootstrap expone editable_entry_source_types + web — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development o
> superpowers:executing-plans. Steps con checkbox (`- [ ]`).

**Goal:** `/bootstrap` expone `editable_entry_source_types` (desde `EDITABLE_ENTRY_SOURCE_TYPES`) y la web lo usa
para mostrar "Editar monto" en cualquier tipo editable, en las 3 secciones del timeline.

**Architecture:** Backend: 1 campo top-level en el response del bootstrap. Web: `CashFlow.vue` lee el array del
bootstrap cacheado (reemplaza el hardcodeo) y agrega la UI de edición a Ingresos y open_debts.

**Tech Stack:** FastAPI · Pydantic v2 · pytest · Vue 3.

**Spec:** `docs/superpowers/specs/2026-06-10-bootstrap-editable-entry-types-design.md`

**Branch:** `feat/bootstrap-editable-entry-types`. Squash-merge al final. **No Notion.**

**Higiene:** backend `cd .../backend && source .venv/bin/activate && pytest -q`; web `cd .../web && npm run build`.
Sin pipes/`2>&1`. Git planos. No push.

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/bootstrap-editable-entry-types
```

---

## Task 1: Backend — `/bootstrap` expone el array (TDD)

**Files:** `backend/tests/test_bootstrap.py`, `backend/app/schemas/bootstrap.py`,
`backend/app/routers/bootstrap.py`

- [ ] **Step 1: Test (rojo)** — en `tests/test_bootstrap.py`, agregar al final de
  `test_bootstrap_returns_catalogs` (tras los asserts de catálogos):

```python
    from app.services.cash_flow_entry_service import EDITABLE_ENTRY_SOURCE_TYPES
    assert body["editable_entry_source_types"] == list(EDITABLE_ENTRY_SOURCE_TYPES)
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_bootstrap.py -q
```

Expected: KeyError `editable_entry_source_types` (el response aún no lo trae).

- [ ] **Step 3: Schema** — en `app/schemas/bootstrap.py`, `BootstrapResponse`:

```python
class BootstrapResponse(BaseModel):
    version: str
    catalogs: Catalogs
    editable_entry_source_types: list[str]
```

- [ ] **Step 4: Router** — en `app/routers/bootstrap.py`, importar la constante e incluir el campo:

```python
from app.services.cash_flow_entry_service import EDITABLE_ENTRY_SOURCE_TYPES
```
```python
    return {
        "version": settings.bootstrap_version,
        "catalogs": bootstrap_service.build_catalogs(db, user),
        "editable_entry_source_types": list(EDITABLE_ENTRY_SOURCE_TYPES),
    }
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_bootstrap.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/schemas/bootstrap.py app/routers/bootstrap.py tests/test_bootstrap.py && git commit -m "feat: /bootstrap expone editable_entry_source_types"
```

---

## Task 2: Web — `CashFlow.vue` usa el array + edición en las 3 secciones

**Files:** `web/src/pages/CashFlow.vue`

- [ ] **Step 1: Script — reemplazar el hardcodeo por el array del bootstrap.**

Cambiar:

```javascript
const EDITABLE_TYPES = ['gasto']
```

por:

```javascript
const editableTypes = ref([])
```

Y en `loadCatalogs`, después de `if (bs?.catalogs) catalogs.value = bs.catalogs`, agregar:

```javascript
  editableTypes.value = bs?.editable_entry_source_types ?? []
```

- [ ] **Step 2: Egresos — usar `editableTypes`.** En la sección de Egresos, cambiar la condición del botón:

```html
                <button v-if="EDITABLE_TYPES.includes(e.source_type)" class="ghost accent" type="button" @click="startEditAmount(e)">
```
por:
```html
                <button v-if="editableTypes.includes(e.source_type)" class="ghost accent" type="button" @click="startEditAmount(e)">
```

- [ ] **Step 3: Ingresos — agregar la UI de edición.** En la sección de Ingresos (`v-for="e in m.incomes"`),
  reemplazar el botón único de Cobros:

```html
              <button class="ghost" type="button" @click="openPayments(e)">Cobros</button>
```
por el patrón con edición:
```html
              <div v-if="editAmountId === e.id" class="field-row">
                <input v-model="amountDraft" type="text" inputmode="decimal" />
                <button class="primary" type="button" @click="saveAmount(e)">Guardar</button>
                <button class="ghost" type="button" @click="cancelEditAmount">Cancelar</button>
              </div>
              <div v-else class="income-actions">
                <button class="ghost" type="button" @click="openPayments(e)">Cobros</button>
                <button v-if="editableTypes.includes(e.source_type)" class="ghost accent" type="button" @click="startEditAmount(e)">
                  Editar monto
                </button>
              </div>
```

- [ ] **Step 4: open_debts — agregar la UI de edición.** En la sección "Para pagar cuando puedas"
  (`v-for="e in timeline.open_debts"`), reemplazar su botón único de Pagos (el que está con **10 espacios** de
  indentación, fuera del `<template>` de meses):

```html
          <p class="muted">pagado {{ formatMoney(e.paid_real, e.currency_id) }} · planificado {{ formatMoney(e.planned_amount, e.currency_id) }}</p>
          <button class="ghost" type="button" @click="openPayments(e)">Pagos</button>
        </div>
      </div>
```
por:
```html
          <p class="muted">pagado {{ formatMoney(e.paid_real, e.currency_id) }} · planificado {{ formatMoney(e.planned_amount, e.currency_id) }}</p>
          <div v-if="editAmountId === e.id" class="field-row">
            <input v-model="amountDraft" type="text" inputmode="decimal" />
            <button class="primary" type="button" @click="saveAmount(e)">Guardar</button>
            <button class="ghost" type="button" @click="cancelEditAmount">Cancelar</button>
          </div>
          <div v-else class="income-actions">
            <button class="ghost" type="button" @click="openPayments(e)">Pagos</button>
            <button v-if="editableTypes.includes(e.source_type)" class="ghost accent" type="button" @click="startEditAmount(e)">
              Editar monto
            </button>
          </div>
        </div>
      </div>
```

> El bloque a reemplazar es **único por su indentación de 10 espacios** (el de Egresos tiene más anidación,
> dentro del `<template>`). Cotejar el contexto (`</div></div>` que cierran la entry y la income-card de
> open_debts) para no tocar el de Egresos.

- [ ] **Step 5: Build**

```bash
cd /Users/tachone/proyectos/margin/web && npm run build
```

Expected: compila sin errores. (Verificación funcional en el navegador, re-logueando para refrescar el
bootstrap cacheado.)

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin && git add web/src/pages/CashFlow.vue && git commit -m "feat(web): editar monto en cualquier tipo editable (array del bootstrap)"
```

---

## Task 3: Suite + cierre

- [ ] **Step 1: Suite backend**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde.

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch. **squash-merge** a
  `main` (1 commit). Push **manual**. Sin Notion.

---

## Self-Review

- **Cobertura del spec:** campo en bootstrap (schema+router+test, Task 1); web lee el array y agrega edición en
  Ingresos/Egresos/open_debts (Task 2). ✓
- **Placeholder scan:** sin TBD/TODO ni código roto. ✓
- **Consistencia:** `editableTypes` (ref, poblado en loadCatalogs) reemplaza `EDITABLE_TYPES`; reusa
  `editAmountId/amountDraft/startEditAmount/saveAmount/cancelEditAmount/updateEntry` ya existentes (funcionan
  para cualquier entry, el estado está keyed por `e.id`). ✓
- **Riesgo:** el bloque de open_debts vs el de Egresos comparten el botón "Pagos"; se distingue por la
  indentación/contexto (open_debts a 10 espacios, fuera del `<template>`). El implementer debe cotejar. ✓

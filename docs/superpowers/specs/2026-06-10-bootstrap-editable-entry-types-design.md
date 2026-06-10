# Bootstrap expone los tipos editables + web los usa — Diseño

> Hoy la web hardcodea `EDITABLE_TYPES = ['gasto']` y solo ofrece "Editar monto" en Egresos, aunque el backend
> ya permite editar **cualquier** `source_type`. Para que no se desincronicen, el backend pasa a exponer su
> array `EDITABLE_ENTRY_SOURCE_TYPES` en el bootstrap, y la web lo lee y muestra "Editar monto" en cualquier
> tipo editable (en todas las secciones del timeline). **Single source of truth: el backend.**

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** backend (1 campo en `/bootstrap` + test) + web (`CashFlow.vue`).
- **Cierre:** rama `feat/bootstrap-editable-entry-types`, **squash-merge** a `main`.

---

## 1. Backend — `/bootstrap` expone `editable_entry_source_types`

El response del bootstrap suma un campo **top-level** (junto a `version` y `catalogs`):

```json
{
  "version": "...",
  "catalogs": { ... },
  "editable_entry_source_types": ["gasto","deuda","deuda_abierta","ingreso","plan_movimiento","plan_movimiento_entrada","tarjeta_credito"]
}
```

- Valor = `EDITABLE_ENTRY_SOURCE_TYPES` del `app/services/cash_flow_entry_service.py` (hoy = todos; si se poda
  el array, el bootstrap lo refleja).
- Es **config estática del cliente**, no un catálogo de BD → va top-level, no dentro de `catalogs`.

**Cambios:**
- `app/schemas/bootstrap.py` → `BootstrapResponse` agrega `editable_entry_source_types: list[str]`.
- `app/routers/bootstrap.py` → incluye `"editable_entry_source_types": list(EDITABLE_ENTRY_SOURCE_TYPES)`
  (importando la constante de `cash_flow_entry_service`).

**Test** (`tests/test_bootstrap.py`): el response trae `editable_entry_source_types` y contiene los tipos
esperados (p.ej. assert que `"gasto"` y `"ingreso"` están, o `== list(EDITABLE_ENTRY_SOURCE_TYPES)`).

> No hace falta tocar `bootstrap_service.build_catalogs` (sigue armando solo los catálogos). El campo nuevo lo
> agrega el router al wrapper.

---

## 2. Web — `CashFlow.vue` usa el array del bootstrap

- **Leer del bootstrap cacheado** en vez de hardcodear: en `loadCatalogs`, además de `catalogs`, guardar
  `editableTypes = bootstrap.editable_entry_source_types ?? []`. Reemplaza la const
  `EDITABLE_TYPES = ['gasto']`.
- El botón "Editar monto" se muestra cuando `editableTypes.includes(e.source_type)`.
- **Agregar la UI de "Editar monto"** (botón + form inline de monto: input + Guardar/Cancelar) también a las
  secciones **Ingresos** y **"Para pagar cuando puedas"** (open_debts) — hoy solo está en **Egresos**. Reusa el
  estado/funciones ya existentes (`editAmountId`, `amountDraft`, `startEditAmount`, `saveAmount`,
  `cancelEditAmount`, `updateEntry`).
- Las acciones por entry quedan uniformes: `Pagos`/`Cobros` + (si editable) `Editar monto`, con el form inline
  al editar.

**Nota de cache:** el bootstrap se cachea en `localStorage`; hay que **re-loguearse** una vez para que la web
traiga el campo nuevo. (Sin re-login, `editable_entry_source_types` viene `undefined` → `?? []` → no se muestra
"Editar monto"; tras re-login aparece.)

---

## 3. Archivos

| Archivo | Cambio |
|---|---|
| `app/schemas/bootstrap.py` | `BootstrapResponse` + `editable_entry_source_types: list[str]` |
| `app/routers/bootstrap.py` | incluir el campo desde `EDITABLE_ENTRY_SOURCE_TYPES` |
| `tests/test_bootstrap.py` | assert del campo |
| `web/src/pages/CashFlow.vue` | leer el array del bootstrap + UI "Editar monto" en las 3 secciones |

Sin migración, sin endpoints nuevos.

---

## 4. Tests

- **Backend** (`tests/test_bootstrap.py`): el response incluye `editable_entry_source_types` y trae los tipos
  esperados.
- **Web:** verificación manual (banco de pruebas): tras re-login, "Editar monto" aparece en ingresos / egresos /
  deuda_abierta / tarjeta, y editar guarda con `PATCH /cash-flow-entries/{id}`.

---

## 5. Plan (orientativo)

Un slice (`feat/bootstrap-editable-entry-types`): TDD del backend (test del campo → schema + router) → web
(leer el array + UI en las 3 secciones) → suite + build → cierre. Sin Notion.

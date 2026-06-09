# GET /cash-flow-entries/by-source + PATCH /cash-flow-entries/{id} — Diseño

> Tercer y último sub-proyecto del grupo **cash-flow-entries**: los 2 endpoints de reestimación de gastos
> variables. `GET /cash-flow-entries/by-source` lista las entries de una fuente editable (mes actual en
> adelante); `PATCH /cash-flow-entries/{entry_id}` edita el monto proyectado de una entry puntual. Cierra el
> grupo de 7 endpoints.

- **Fecha:** 2026-06-09
- **Estado:** aprobado para implementar
- **Alcance:** **backend only** (la web del flujo va después). Los 2 endpoints en **un** slice.
- **Cierre:** rama `feat/cash-flow-entries-edit`, **squash-merge** a `main`.
- **Fuente de verdad (Notion):** `Endpoints → Flujo de dinero →` {GET cash-flow-entries by-source,
  PATCH cash-flow-entries}, y `GLOBAL → Tipos de cash_flow_entries editables por el usuario`.
- **Depende de:** `cash_flow_entries` (materializadas), `obligations`/`obligation_types`. Extiende los archivos
  del slice `GET /cash-flow-entries` (service/router/schema).

---

## 1. Concepto compartido: tipos editables

`EDITABLE_ENTRY_SOURCE_TYPES = ("gasto",)` — constante del backend que espeja GLOBAL (hoy solo gastos
variables; mañana se suma `'ingreso'` y ambos endpoints lo respetan sin cambios). Se define en
`app/services/cash_flow_entry_service.py` (al lado de las funciones que la usan).

Edición **blanda**: lo editado vive sobre la fila materializada (territorio del `CashFlowEngine`); si la fuente
se reproyecta, el motor pisa estas ediciones. No se persiste ninguna marca de "editado a mano"; la advertencia
es del frontend. Estos endpoints **no corren el motor**.

`today`: las dos funciones del service toman `today: date | None = None` (default `date.today()`) para tests
deterministas, como los motores. El recorte "mes actual en adelante" usa `today.replace(day=1)`.

---

## 2. Schema compartido (`app/schemas/cash_flow_entry.py`)

```text
SourceEntryOut(BaseModel):
    id: uuid.UUID
    event_date: date
    amount: Decimal
    currency_id: int
    source_type: str
```

Ambos endpoints devuelven esta forma liviana (sin `paid_real`/`planned_amount`, sin `*_converted`: no hay plan
ni capa de simulación acá). Se agrega a las schemas ya existentes del slice anterior.

Body del PATCH:

```text
EntryAmountUpdate(BaseModel):
    amount: Decimal     # requerido
```

---

## 3. GET /cash-flow-entries/by-source?source_id={source_id} → 200 `[SourceEntryOut]`

Solo lectura. Lista las entries de **una** fuente editable, del mes actual en adelante, para reestimar.

**Validaciones (en orden):**
1. `source_id` vino en la query. Si falta → 422 `source_id_required`.
2. La fuente existe y es del usuario. Hoy las fuentes editables son `gasto` = `obligations` con
   `obligation_kind = 'gasto'`. Resolución: `SELECT` sobre `obligations` join `obligation_types` con
   `obligations.id = source_id` y `obligations.user_id = user`. Si no existe / no es del usuario → 404
   `not_found`.
3. El `source_type` de la fuente (= su `obligation_kind`) está en `EDITABLE_ENTRY_SOURCE_TYPES`. Si no → 422
   `source_not_editable`. (Ej.: un `source_id` de una `deuda` resuelve la obligación pero su kind no es
   editable.)

> Un `source_id` que apunta a una fuente no-obligación (income/credit_card) no resuelve en el paso 2 → 404. El
> frontend solo ofrece "editar futuros" sobre gastos, así que es un caso borde defensivo.

**Lectura:** `cash_flow_entries` con `user_id = user`, `source_id = source_id`,
`source_type IN EDITABLE_ENTRY_SOURCE_TYPES` (defensa redundante con el paso 3) y
`event_date >= today.replace(day=1)`. Orden `event_date ASC`. Devolver `SourceEntryOut` por fila. `[]` si no
hay entries del mes actual en adelante.

---

## 4. PATCH /cash-flow-entries/{entry_id} → 200 `SourceEntryOut`

Edita el `amount` proyectado de una entry. No corre el motor.

**Validaciones (en orden):**
1. La entry existe y `cfe.user_id == user`. Si no → 404 `not_found`.
2. `entry.source_type ∈ EDITABLE_ENTRY_SOURCE_TYPES`. Si no → 422 `source_not_editable`.
3. La entry es del mes actual o futura: `event_date >= today.replace(day=1)`. Si es de un mes pasado (o
   `event_date is None`) → 409 `entry_not_editable`.
4. `amount > 0`. Si no → 422 `amount_invalid`.

**Update:** `amount` y `updated_at = now()`. No se toca `event_date`, `currency_id`, `source_*`. Sin recálculo.
Devolver `SourceEntryOut`.

> `amount` es obligatorio en el body (lo exige Pydantic; si falta → 422 de validación). No hay `empty_patch`
> acá (un solo campo, requerido).

---

## 5. Códigos de error nuevos (`errors.py`)

| code | HTTP | mensaje |
|---|---|---|
| `source_id_required` | 422 | Falta indicar la fuente. |
| `source_not_editable` | 422 | Este tipo de movimiento no se puede editar. |
| `entry_not_editable` | 409 | No se puede editar un mes ya pasado. |

Reuso: `amount_invalid` (422), `not_found` (404), `unauthenticated` (401).

---

## 6. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow_entry_service.py` | + `EDITABLE_ENTRY_SOURCE_TYPES`, `list_by_source(...)`, `update_entry_amount(...)` |
| `app/routers/cash_flow_entries.py` | + `GET /cash-flow-entries/by-source`, `PATCH /cash-flow-entries/{entry_id}` |
| `app/schemas/cash_flow_entry.py` | + `SourceEntryOut`, `EntryAmountUpdate` |
| `app/core/errors.py` | + 3 codes |

Routing: `GET /cash-flow-entries/by-source` es un segmento literal; no choca con `GET /cash-flow-entries`
(slice anterior) ni con el `PATCH /cash-flow-entries/{entry_id}` (método distinto). Sin ambigüedad.

---

## 7. Tests

Postgres `margin_test` (`create_all` + savepoint). Setup: gasto = `obligations` (kind `gasto`) — crear vía el
servicio existente o insertar fila + catálogos mínimos (mirar tests de gastos/obligaciones); entries vía
`CashFlowEntry(...)` apuntando a la fuente. Pasar `today` a las funciones para fijar el mes.

**by-source** (`tests/test_cash_flow_entries_by_source.py`):
- 422 `source_id_required` (sin query param).
- 404 fuente inexistente / de otro usuario / `source_id` que no es una obligación.
- 422 `source_not_editable` (source_id de una `deuda`).
- Lista mes actual + futuros, **excluye** los meses pasados; orden `event_date ASC`.
- `[]` cuando no hay entries del mes actual en adelante.
- Forma `SourceEntryOut` (sin `paid_real`/`planned_amount`/convertidos).

**PATCH** (`tests/test_patch_cash_flow_entry.py`):
- 200 edita `amount` (futuro) y lo refleja.
- 404 entry inexistente / de otro usuario.
- 422 `source_not_editable` (entry cuyo `source_type` no es `gasto`, p.ej. `tarjeta_credito`).
- 409 `entry_not_editable` (entry de un mes pasado).
- 422 `amount_invalid` (0 y negativo).
- (Opcional) edita una entry del mes actual (no solo futura).

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/cash-flow-entries-edit`), TDD: schema + codes → `list_by_source` + GET + tests → 
`update_entry_amount` + PATCH + tests → suite verde → cierre. Notion ya documenta ambos endpoints tal cual;
no requiere actualización.

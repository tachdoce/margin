# cash_flow_entries — editar cualquier grupo — Diseño

> Hoy solo `gasto` es editable (`EDITABLE_ENTRY_SOURCE_TYPES = ("gasto",)`) y `by-source` resuelve la fuente
> únicamente contra `obligations`. El usuario quiere **poder editar todas las entries** (para después ver cuáles
> conviene quitar) y que `by-source` sirva para **cualquier grupo**, no solo obligaciones.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** backend; `app/services/cash_flow_entry_service.py` (la tupla de editables + `list_by_source`
  genérico) + tests. Sin migración, sin endpoints nuevos.
- **Cierre:** rama `feat/cash-flow-entries-editable-all`, **squash-merge** a `main`.
- **Contexto:** `by-source` **no** se usa en la web (la web edita con `PATCH /cash-flow-entries/{id}` inline).
  Se hace genérico igual, para dejarlo coherente.

---

## 1. Cambio 1 — todos los tipos editables

`EDITABLE_ENTRY_SOURCE_TYPES` pasa a contener **todos** los `cash_flow_source_type`. Implementación DRY:
reusar la tupla del modelo.

```python
from app.models.cash_flow_entry import CASH_FLOW_SOURCE_TYPES  # ya se importa CashFlowEntry de ahí

EDITABLE_ENTRY_SOURCE_TYPES = CASH_FLOW_SOURCE_TYPES
# = ("gasto","deuda","deuda_abierta","ingreso","plan_movimiento","plan_movimiento_entrada","tarjeta_credito")
```

- **Efecto:** cualquier entry queda editable por `PATCH /cash-flow-entries/{id}` (sigue el gate de mes actual y
  `amount > 0`). Edición **blanda** como hasta ahora (el motor pisa el monto si reproyecta la fuente).
- **`source_not_editable` queda inalcanzable** mientras estén todos los tipos. **Se mantiene** el code y los dos
  chequeos que lo levantan: el día que el usuario pode la tupla, vuelven a tener efecto. (Es exploratorio: "todos
  editables para ver cuáles quitar".)
- Reusar la tupla del modelo mantiene "todos" automáticamente si se agrega un `source_type` nuevo al enum.

---

## 2. Cambio 2 — `by-source` genérico (resuelve vía las entries)

Hoy `list_by_source` resuelve la fuente con un JOIN a `obligations`/`obligation_types` (toma el
`obligation_kind`), por eso solo funciona con gasto/deuda/deuda_abierta. Como `cash_flow_entries` es
**polimórfica** (cada fila trae `user_id`, `source_type`, `source_id`), la fuente se puede resolver **desde las
propias entries**, sirviendo para cualquier grupo.

Nueva resolución en `list_by_source(db, user, source_id, *, today=None)`:
1. `source_id` en la query → si falta, 422 `source_id_required` (sin cambios).
2. Resolver el `source_type` de la fuente desde las entries: leer **un** `source_type` de
   `cash_flow_entries` con `source_id = {source_id}` y `user_id = user`. Si **no hay ninguna** → 404
   `not_found`. (Una fuente mapea a un solo `source_type`; alcanza con tomar el de cualquier fila — p.ej.
   `LIMIT 1`.)
3. Si ese `source_type` ∉ `EDITABLE_ENTRY_SOURCE_TYPES` → 422 `source_not_editable`.
4. Listar las entries de esa fuente del **mes actual en adelante** (sin cambios): `user_id = user`,
   `source_id = {source_id}`, `source_type IN EDITABLE_ENTRY_SOURCE_TYPES` (defensa), `event_date >=`
   primer día del mes actual; orden `event_date ASC`.

**Se elimina** el JOIN a `Obligation`/`ObligationType` (y sus imports si quedan sin uso). El resto del endpoint
(schema `SourceEntryOut`, orden, recorte por mes) no cambia.

> **Resolución por entries vs por fuente:** una fuente editable siempre tiene entries materializadas (el motor
> las crea), así que resolver por entries es sólido. Una fuente cuyas entries son todas pasadas igual resuelve
> (las entries existen) y devuelve `[]` (no hay del mes actual en adelante) — no 404. Un `source_id` sin
> entries del usuario → 404, que es el comportamiento correcto.

---

## 3. Efecto combinado

Se puede **listar** (`by-source`) y **editar** (`PATCH`) cualquier grupo de entries del usuario, sin importar el
`source_type`. La pretensión "editar todo para ver qué quitar" queda cubierta de punta a punta.

---

## 4. Tests (`tests/test_cash_flow_entries_by_source.py`, `tests/test_patch_cash_flow_entry.py`)

- **Actualizar** `test_cash_flow_entries_by_source.py::test_source_not_editable` (hoy: fuente `deuda` →
  `source_not_editable`). Con todo editable, una `deuda` ahora **lista sus entries** (200). Repurpose: assert que
  resuelve y devuelve la lista (editable).
- **Agregar** un test de `by-source` **genérico**: una fuente **no-obligación** (p.ej. `ingreso` o
  `tarjeta_credito`) con entries del mes actual → `by-source` resuelve y las lista (antes daba 404 porque no era
  obligación).
- **Mantener** los casos que no cambian: `source_id_required`, 404 cuando no hay entries para ese `source_id`,
  recorte mes-actual / orden.
- **Actualizar** `test_patch_cash_flow_entry.py::test_patch_source_not_editable` (hoy: entry `tarjeta_credito` →
  `source_not_editable`). Ahora `tarjeta_credito` es editable → el PATCH debe **funcionar** (200, actualiza el
  monto), sujeto al gate de mes (usar una entry del mes actual/futura).
- **Mantener** `test_patch_past_month_not_editable` (`entry_not_editable`) y `amount_invalid` — no dependen del
  tipo.

> `source_not_editable` queda sin test que lo dispare (es inalcanzable con todos los tipos). Se deja el code y
> los chequeos en el servicio; cuando se pode la tupla, se volverá a testear.

---

## 5. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow_entry_service.py` | `EDITABLE_ENTRY_SOURCE_TYPES = CASH_FLOW_SOURCE_TYPES`; `list_by_source` resuelve vía entries (quita el JOIN a obligations) |
| `tests/test_cash_flow_entries_by_source.py` | actualizar `source_not_editable` → editable + test genérico |
| `tests/test_patch_cash_flow_entry.py` | actualizar `source_not_editable` → editable |

---

## 6. Plan (orientativo)

Un slice (`feat/cash-flow-entries-editable-all`), TDD: actualizar/agregar tests (rojo) → tupla = todos +
`list_by_source` genérico (verde) → suite completa → cierre. Sin Notion.

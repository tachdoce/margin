# Quitar tarjeta_credito de los editables — Diseño

> Tras la fase exploratoria "todos editables para ver cuáles quitar", se poda el primero: las entries de
> **`tarjeta_credito`** dejan de ser editables. El monto de una entry de tarjeta sale del **resumen real del
> banco** (lo materializa `CashFlowEngine.credit_cards`); editarlo a mano no aporta y el motor lo pisa al
> reproyectar.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** backend; `app/services/cash_flow_entry_service.py` (la tupla) + tests. **Sin cambios en la web**
  (lee el array del bootstrap → tras re-login deja de ofrecer "Editar monto" en tarjeta).
- **Cierre:** rama `feat/prune-credit-card-editable`, **squash-merge** a `main`.

---

## 1. Cambio

`EDITABLE_ENTRY_SOURCE_TYPES` pasa de "todos" (`CASH_FLOW_SOURCE_TYPES`) a una **tupla explícita sin
`tarjeta_credito`** (los otros 6):

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

- El import `from app.models.cash_flow_entry import CASH_FLOW_SOURCE_TYPES, CashFlowEntry` vuelve a ser
  `from app.models.cash_flow_entry import CashFlowEntry` (`CASH_FLOW_SOURCE_TYPES` queda sin uso).
- **Efecto:** `PATCH /cash-flow-entries/{id}` y `GET /cash-flow-entries/by-source` rechazan las fuentes/entries
  de tarjeta con 422 `source_not_editable` (que vuelve a ser **alcanzable**). Los otros 6 tipos siguen
  editables.
- **Bootstrap:** `editable_entry_source_types` se sirve desde esta constante, así que el response (y la web) lo
  reflejan solos — sin tocar el bootstrap ni la web.

---

## 2. Tests

- **`tests/test_patch_cash_flow_entry.py`:** revertir `test_patch_credit_card_now_editable` →
  `test_patch_credit_card_not_editable`: una entry `tarjeta_credito` (mes actual/futuro) ahora da 422
  `source_not_editable`.
- **`tests/test_cash_flow_entries_by_source.py`:** agregar `test_by_source_credit_card_not_editable`: una fuente
  con entries `tarjeta_credito` → 422 `source_not_editable` (cubre el camino podado en by-source).
- **`tests/test_bootstrap.py`:** sin cambios — assertea `== list(EDITABLE_ENTRY_SOURCE_TYPES)`, se ajusta solo.
- Los tests de los tipos que siguen editables (`test_deuda_source_now_listed`, `test_by_source_generic_non_obligation`
  con `ingreso`, los PATCH de gasto) no cambian.

---

## 3. Archivos

| Archivo | Cambio |
|---|---|
| `app/services/cash_flow_entry_service.py` | tupla explícita sin `tarjeta_credito`; revertir import |
| `tests/test_patch_cash_flow_entry.py` | tarjeta → `source_not_editable` |
| `tests/test_cash_flow_entries_by_source.py` | + by-source tarjeta → `source_not_editable` |

Sin migración, sin endpoints nuevos, sin web.

---

## 4. Plan (orientativo)

Un slice (`feat/prune-credit-card-editable`), TDD: actualizar/agregar tests (rojo) → tupla explícita + revertir
import (verde) → suite completa → cierre. Sin Notion.

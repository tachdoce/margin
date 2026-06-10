# `is_auto_generated` en `plan_movements` y `cash_flow_payments` — Diseño

> Agregar un boolean `is_auto_generated` a `plan_movements` y `cash_flow_payments` para marcar las filas
> generadas por el **PlanningEngine** (el motor que decidirá/optimizará qué pagar y generará esas filas;
> ver memoria `planning-engine-concept`). El flag permite que, cuando ese motor corra, borre **solo lo suyo**
> (`is_auto_generated = true`) de un plan y lo recree, dejando intactas las filas manuales del usuario.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only.** Solo las columnas + su exposición read-only. La lógica de borrado-y-recreación
  y el PlanningEngine **quedan fuera** (no existen aún).
- **Cierre:** rama `feat/is-auto-generated-flag`, **squash-merge** a `main`.

---

## 1. Propósito y contrato

El PlanningEngine (futuro) generará `plan_movements` y `cash_flow_payments` planificados. Para poder regenerarlos
de forma idempotente sin pisar lo que el usuario creó a mano, cada fila lleva `is_auto_generated`:

- `true` → la generó un motor; es **regenerable** (el motor la puede borrar y recrear).
- `false` (default) → **manual**, creada por el usuario; ningún motor la toca.

El flag **no es derivable**: en `cash_flow_payments` un pago planificado (`plan_id` seteado) puede ser manual o
del motor; en `plan_movements` todas las altas actuales son manuales. Por eso hace falta la columna explícita.

---

## 2. Modelo (ambas tablas)

```python
is_auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```

- NOT NULL + `server_default="false"`, sin default Python — mismo patrón que `currency.is_legal_tender`,
  `currency.allowed_in_credit_card`, `country.visible`.
- Las filas preexistentes en dev quedan en `false` por el `server_default`.
- Un alta por el ORM que omita el campo cae en `false` (DB default). El PlanningEngine setea `True` explícito.

---

## 3. Migración

`alembic revision --autogenerate -m "is_auto_generated en plan_movements y cash_flow_payments"` → revisar que
agregue la columna a **ambas** tablas con `server_default="false"` → `alembic upgrade head`. El server_default
resuelve las filas preexistentes en dev sin pasos manuales.

---

## 4. Schemas

| Schema | Cambio |
|---|---|
| `PlanMovementCreate` / `PlanMovementUpdate` | **sin cambios** — el usuario nunca setea el flag |
| `PaymentCreate` / `PaymentUpdate` | **sin cambios** — idem |
| `PlanMovementOut` | agregar `is_auto_generated: bool` (read-only) + en `from_model` |
| `PaymentOut` | agregar `is_auto_generated: bool` (read-only) + en `from_model` |
| `PaymentListItem` | agregar `is_auto_generated: bool` (read-only) + en `from_model` |

**Read-only:** el flag se expone en los OUT (el propósito es *identificar* qué filas hizo el motor) pero
**nunca** se acepta como input. Un alta manual siempre nace `false`; el usuario no puede setearlo ni editarlo.
Es análogo a `is_planned` en `PaymentListItem`, que ya es un campo derivado read-only.

---

## 5. Tests

- **`plan_movements`:** alta manual vía el flujo existente → `is_auto_generated == False`; insertar una fila con
  `is_auto_generated=True` directo y verificar que persiste y round-trips.
- **`cash_flow_payments`:** alta manual de pago (real y planificado) → `is_auto_generated == False`.
- **Schemas Out:** `PlanMovementOut`/`PaymentOut`/`PaymentListItem` serializan `is_auto_generated`; los Create/Update
  lo ignoran (un payload que lo incluya no lo persiste — no está en el schema).

---

## 6. Fuera de alcance

- La lógica de **wipe-and-recreate** (borrar `is_auto_generated=true` de un plan y recrear).
- El **PlanningEngine** en sí (decisión/optimización, generación desde financings/deudas/settings).
- Cualquier endpoint nuevo.

---

## 7. Archivos

| Archivo | Cambio |
|---|---|
| `app/models/plan_movement.py` | + columna `is_auto_generated` |
| `app/models/cash_flow_payment.py` | + columna `is_auto_generated` |
| `alembic/versions/<rev>_*.py` | migración (autogenerate) para ambas tablas |
| `app/schemas/plan_movement.py` | `PlanMovementOut` + campo y `from_model` |
| `app/schemas/cash_flow_payment.py` | `PaymentOut` + `PaymentListItem` + campo y `from_model` |
| `tests/...` | tests de default false, persistencia de true, exposición read-only |

---

## 8. Plan (orientativo)

Un slice (`feat/is-auto-generated-flag`), TDD: tests de default/persistencia/exposición (rojo) → columnas en los
modelos + migración + campos en los OUT (verde) → suite completa → cierre (squash-merge). Sin Notion, sin web.

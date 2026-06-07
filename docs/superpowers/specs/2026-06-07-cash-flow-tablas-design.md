# Slice 1 — Tablas `cash_flow_entries` + `cash_flow_payments` — Diseño

> Primer slice de conectar **Ingresos** con la **línea de tiempo del flujo de caja**. Acá solo se crean las
> dos tablas (modelos + enum + migración). El motor de materialización y el cableado de los endpoints van en
> slices posteriores (resumidos al final, **no entran en este spec**). El *qué* del producto vive en
> Notion → BD → Flujo de dinero → `cash_flow_entries` / `cash_flow_payments`.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** `users`, `currencies`, `plans` (en `main`).
- **Cierre:** rama `feat/cash-flow-tablas`, **squash-merge** a `main`.

---

## 1. Alcance

Modelos SQLAlchemy `CashFlowEntry` y `CashFlowPayment`, el enum nativo `cash_flow_source_type`, una migración
Alembic que crea el enum + ambas tablas (`cash_flow_entries` primero por la FK), y el registro de ambos
modelos en `app/models/__init__.py`. **No entra:** endpoints, schemas, servicio, seed, ni el motor.

**Decisión (aprobada):** la tabla se crea **completa** — los 7 `source_type` y todas las columnas, incluidas
las que hoy solo usan tarjetas (`issue_year`, `issue_month`, `minimum_payment`). Coincide con la spec de BD y
con cómo se hizo `plans`/`plan_movements` (tabla completa, comportamiento diferido); evita re-migrar al sumar
los otros motores. Solo el motor de ingresos (slice futuro) la escribirá, pero la tabla nace para toda la
familia.

---

## 2. Enum nativo

```sql
CREATE TYPE cash_flow_source_type AS ENUM (
  'gasto', 'deuda', 'deuda_abierta', 'ingreso',
  'plan_movimiento', 'plan_movimiento_entrada', 'tarjeta_credito'
);
```

Patrón de `plan_goal_kind`/`plan_movement_kind`: la migración lo crea, el `downgrade` lo dropea tras las tablas.

---

## 3. Tabla `cash_flow_entries`

| columna | tipo | null | notas |
|---|---|---|---|
| id | `uuid` PK default `uuid4` | no | |
| user_id | `uuid` FK→`users.id` | no | denormalizado para query por usuario sin JOINs |
| event_date | `date` | sí | día proyectado del evento; NULL solo en `deuda_abierta` |
| is_income | `boolean` | no | `true` entra, `false` sale (sin `server_default`: lo setea el motor) |
| amount | `numeric(12,2)` | no | siempre positivo; el signo lo deriva `is_income` |
| currency_id | `smallint` FK→`currencies.id` | no | |
| financing_rate | `numeric(5,2)` | sí | NULL en ingresos |
| overdue_rate | `numeric(5,2)` | sí | NULL en ingresos |
| issue_year | `smallint` | sí | solo tarjetas; NULL en el resto |
| issue_month | `smallint` | sí | solo tarjetas; NULL en el resto |
| minimum_payment | `numeric(12,2)` | sí | solo tarjetas; NULL en el resto |
| source_type | `cash_flow_source_type` | no | de qué fuente nació |
| source_id | `uuid` | no | **sin FK** (polimórfico); junto a `source_type` identifica el origen |
| created_at | `timestamp(tz)` | no | `server_default now()` |
| updated_at | `timestamp(tz)` | no | `server_default now()`, `onupdate now()` |

---

## 4. Tabla `cash_flow_payments`

| columna | tipo | null | notas |
|---|---|---|---|
| id | `uuid` PK default `uuid4` | no | |
| cash_flow_entry_id | `uuid` FK→`cash_flow_entries.id` **ON DELETE CASCADE** | no | a qué entry se imputa |
| amount | `numeric(12,2)` | no | siempre positivo; hereda moneda de la entry |
| note | `varchar(100)` | sí | texto libre opcional |
| plan_id | `uuid` FK→`plans.id` | sí | NULL = pago real; con valor = planificado de ese plan |
| planned_date | `date` | sí | viaja junto con `plan_id` (ambas NULL o ambas con valor) |
| created_at | `timestamp(tz)` | no | `server_default now()` |
| updated_at | `timestamp(tz)` | no | `server_default now()`, `onupdate now()` |

Tipos SQLAlchemy: `UUID(as_uuid=True)`, `SmallInteger`, `Numeric(12,2)`/`Numeric(5,2)`, `String(100)`,
`Boolean`, `Date`, `DateTime(timezone=True)`, `func.now()`, `Enum(..., name="cash_flow_source_type")`.
La FK de `cash_flow_entry_id` lleva `ondelete="CASCADE"`.

---

## 5. Decisiones (consistentes con incomes/plans)

- **Sin `server_default` en `is_income`:** lo setea siempre el motor. NOT NULL sin default en BD.
- **`source_id` sin FK:** origen polimórfico (4 tablas), Postgres no soporta FK polimórfica; la integridad la
  mantiene el backend (la familia `CashFlowEngine`, slice futuro).
- **`cash_flow_payments.cash_flow_entry_id` con `ON DELETE CASCADE`:** lo requerirá el borrado del income
  ("al borrar la entry, sus pagos se van por cascade"). Se deja listo desde ya.
- **Sin CHECK ni UNIQUE:** la consistencia (NULL semántico de tasas/columnas de tarjeta por `source_type`,
  `plan_id`+`planned_date` de a dos, unicidad de la clave lógica de cada motor) vive en el backend, no en BD.

---

## 6. Verificación

- `alembic revision --autogenerate -m "create cash_flow_entries and cash_flow_payments"` → **revisar**: crea
  el enum, las 2 tablas, las FKs (`cash_flow_entries.user_id`/`currency_id`,
  `cash_flow_payments.cash_flow_entry_id` con CASCADE, `plan_id`), **sin** FK en `source_id`, nullables
  correctos, y `downgrade` que dropea tablas y luego el enum → `alembic upgrade head` sobre `margin`.
- `psql -d margin`: `\d cash_flow_entries`, `\d cash_flow_payments`, `\dT cash_flow_source_type`.
- **Test de round-trip** en `tests/test_cash_flow_model.py`: insertar un `CashFlowEntry` `ingreso` (con
  `user`+`currency` sembrados) y un `CashFlowPayment` que apunte a ella; releer; confirmar que persisten, que
  los nullables aceptan NULL, y que **borrar la entry borra el payment por cascade**. Regresión `pytest -q`.

---

## 7. Hacia dónde vamos (contexto, NO entra en este spec)

Los siguientes slices se especificarán y aprobarán por separado, cada uno con su propio diseño:

- **Slice 2 — `CashFlowEngine.incomes`:** función canónica `compute_event_date` + `materialize_income`, que
  traduce cada `incomes` vigente en filas de `cash_flow_entries` (UPSERT por clave lógica, horizonte
  2027-12-31).
- **Slice 3 — endpoints de ingresos con el motor + borrado híbrido:** create/update/reactivate ejecutan el
  motor en su transacción; `delete` pasa al hard/soft real (hard si no hay pagos reales, soft si los hay).

Se mencionan solo para que el diseño de las tablas (este spec) sea coherente con su uso futuro.

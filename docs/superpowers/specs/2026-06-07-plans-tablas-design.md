# Tablas `plans` + `plan_movements` (slice tabla, subdominio Flujo de dinero) — Diseño

> Primer slice del subdominio "Flujo de dinero": solo los modelos y la migración de `plans` y
> `plan_movements`. Endpoints, validación y el `CashFlowEngine`/`PlanEngine` van en slices/proyectos
> posteriores. El *qué* del producto vive en Notion → BD → Flujo de dinero → plans / plan_movements.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** `users`, `currencies` (en `main`).
- **Cierre:** rama `feat/plans-tablas`, **squash-merge** a `main`.

---

## 1. Alcance

**Entra:** modelos SQLAlchemy `Plan` y `PlanMovement`, los 2 enums nativos, una migración Alembic que crea
los enums + ambas tablas (`plans` primero por la FK), y el registro de ambos modelos en
`app/models/__init__.py`. Las dos juntas porque `plan_movements.plan_id` → `plans`.

**No entra:** endpoints, schemas, servicio, validaciones, seed. **Diferido a slices/proyectos posteriores:**
plan default creado al registrarse, validación del objetivo (las 3 columnas goal juntas) y de columnas por
`kind`, derivación de monedas por el backend, borrado orquestado, y la materialización a `cash_flow_entries`
(necesita esas tablas + el engine).

---

## 2. Enums nativos (patrón de `obligation_kind` / `auth_provider`)

```sql
CREATE TYPE plan_goal_kind AS ENUM ('ahorro_total');
CREATE TYPE plan_movement_kind AS ENUM ('ingreso', 'deuda_informal', 'prestamo');
```

La migración los crea; el `downgrade` los dropea (después de dropear las tablas que los usan).

---

## 3. Tabla `plans` (fuente: Notion → BD → Flujo de dinero → plans)

| columna | tipo | null | notas |
|---|---|---|---|
| id | `uuid` PK default `uuid4` | no | |
| user_id | `uuid` FK→`users.id` | no | a quién pertenece |
| name | `varchar(80)` | no | nombre del plan |
| is_default | `boolean` | no | el backend garantiza 1 por usuario (no constraint de BD) |
| is_engine_generated | `boolean` | no | origen: usuario vs PlanEngine |
| selected_at | `timestamp(tz)` | no | el front interpreta "activo" = mayor `selected_at` |
| dial_amount | `numeric(12,2)` | no | ≥ 0 (lo valida el servicio) |
| dial_currency_id | `smallint` FK→`currencies.id` | no | lo deriva el backend (moneda del país) |
| goal_kind | `plan_goal_kind` | sí | las 3 goal viajan juntas (las 3 o NULL) |
| goal_amount | `numeric(12,2)` | sí | > 0 cuando no es NULL (valida el servicio) |
| goal_currency_id | `smallint` FK→`currencies.id` | sí | |
| created_at | `timestamp(tz)` | no | `server_default now()` |
| updated_at | `timestamp(tz)` | no | `server_default now()`, `onupdate now()` |

---

## 4. Tabla `plan_movements` (fuente: Notion → BD → Flujo de dinero → plan_movements)

| columna | tipo | null | notas |
|---|---|---|---|
| id | `uuid` PK default `uuid4` | no | |
| plan_id | `uuid` FK→`plans.id` | no | a qué plan pertenece |
| kind | `plan_movement_kind` | no | define qué columnas se usan |
| currency_id | `smallint` FK→`currencies.id` | no | |
| description | `varchar(100)` | sí | texto libre opcional |
| principal_amount | `numeric(12,2)` | no | monto base (entra / se debe / capital) |
| start_date | `date` | no | fecha base |
| income_duration_months | `smallint` | sí | lado ingreso: 1 / N / NULL |
| installment_amount | `numeric(12,2)` | sí | solo en `prestamo` |
| installment_start_date | `date` | sí | solo en `prestamo` |
| total_installments | `smallint` | sí | solo en `prestamo` |
| financing_rate | `numeric(5,2)` | sí | % anual, solo en `prestamo` |
| overdue_rate | `numeric(5,2)` | sí | % punitorio, solo en `prestamo` |
| rates_add_vat | `boolean` | no | si a las tasas hay que sumarles IVA |
| created_at | `timestamp(tz)` | no | `server_default now()` |
| updated_at | `timestamp(tz)` | no | `server_default now()`, `onupdate now()` |

Tipos SQLAlchemy: `UUID(as_uuid=True)`, `SmallInteger`, `Numeric(12, 2)` / `Numeric(5, 2)`, `String(80)` /
`String(100)`, `Boolean`, `Date`, `DateTime(timezone=True)`, `func.now()`, y `Enum(..., name="...")` para
los nativos.

---

## 5. Decisiones (consistentes con el slice tabla de incomes)

- **Sin defaults de BD en los booleanos** (`is_default`, `is_engine_generated`, `rates_add_vat`): los setea
  el backend en el slice de endpoints, como en incomes. Notion dice "default false/true" describiendo el
  valor que asigna el backend, no un `DEFAULT` en BD. En BD: `NOT NULL` sin `server_default`.
- **Sin CHECK constraints:** la consistencia (goal de a 3, columnas por `kind`, `dial_amount ≥ 0`,
  `goal_amount > 0`) vive en el servicio (slice futuro), como define Notion ("sin CHECKs a nivel BD"). Las
  tablas solo llevan FKs, `NOT NULL`, PKs y los enums nativos.
- **`is_default` sin UNIQUE parcial:** Notion dice explícitamente que "1 default por usuario" lo garantiza el
  backend, no un constraint. No se agrega índice único parcial en este slice.
- **Plata `numeric(12,2)`, tasas `numeric(5,2)`** (Decimal, nunca float).
- **FKs sin `ON DELETE` especial:** el borrado orquestado (pagos→entries→movements→plan) es del backend
  (Notion), no de la BD.
- **Enums nativos** (no tablas ni CHECK): mismo criterio que `obligation_kind`/`auth_provider`.

---

## 6. Verificación

- `alembic revision --autogenerate -m "plans and plan_movements"` → **revisar**: que cree los 2 enums, las
  2 tablas con sus FKs (`plans.user_id`/`dial_currency_id`/`goal_currency_id`, `plan_movements.plan_id`/
  `currency_id`), los `NOT NULL`/nullable correctos, y que el `downgrade` dropee tablas y luego enums →
  `alembic upgrade head` sobre `margin`.
- `psql -d margin`: `\d plans` y `\d plan_movements` (columnas, tipos, FKs); `\dT plan_goal_kind` y
  `\dT plan_movement_kind` (labels de cada enum).
- **Test de round-trip** en `tests/test_plans_model.py`: insertar un `Plan` (con `user` + `currency`
  sembrados) y un `PlanMovement` que apunte a ese plan, releerlos; confirmar que persisten y que los
  nullables aceptan NULL. Regresión: `pytest -q` verde.

---

## 7. Fuera de alcance (recordatorio explícito)

Endpoints (`POST/GET/PATCH/DELETE /plans`, movimientos), validación de objetivo y de columnas por `kind`,
plan default al registrarse, derivación de monedas, borrado orquestado, y materialización a
`cash_flow_entries` (requiere las tablas `cash_flow_*` + `CashFlowEngine`/`PlanEngine`).

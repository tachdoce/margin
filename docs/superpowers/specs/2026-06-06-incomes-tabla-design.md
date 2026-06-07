# Tabla `incomes` (slice 1 de Ingresos) — Diseño

> Primer slice del subdominio de ingresos: solo el modelo y la migración de la tabla `incomes`.
> Los endpoints (POST/GET/PATCH/DELETE) y su lógica de validación van en el **slice 2**. El *qué* del
> producto vive en Notion → BD → Ingresos → incomes y → Endpoints → Ingresos.

- **Fecha:** 2026-06-06
- **Estado:** aprobado para implementar
- **Depende de:** `users`, `income_types`, `currencies` (todas en `main`).
- **Cierre:** rama `feat/incomes-tabla`, **squash-merge** a `main`.

---

## 1. Contexto y descomposición

`incomes` es la fuente de ingreso del usuario (sueldo, freelance, alquiler que cobra, aguinaldo, etc.):
cada usuario tiene N filas, una por fuente. La feature completa (tabla + 5 endpoints) se parte en slices:

- **Slice 1 (este spec):** modelo `Income` + migración Alembic + registro en `app/models/__init__.py`.
- **Slice 2 (futuro):** `POST /incomes` + `PATCH /incomes/{id}` — se agrupan porque comparten la validación
  de forma del modelo binario (recurrente infinito / duración fija) + los error codes de validación.
- **Slice 3 (futuro):** `GET /incomes` (listado del usuario con `is_deleted` derivado) + un
  `DELETE /incomes/{id}` **provisorio**: hard-delete simple para poder ejercitar/limpiar el endpoint
  durante el desarrollo. Conserva solo el filtro por `user_id` del token (+ 404 si no existe); **sin** la
  lógica real (cascada de `cash_flow_entries`, rama soft-delete, conteo de `cash_flow_payments`).

> El `DELETE` del slice 3 es **descartable**: cuando exista el CashFlowEngine + tablas `cash_flow_*` se
> reemplaza por el DELETE completo (hard-delete + rama soft-delete según pagos reales + cascada). El filtro
> por `user_id` se mantiene siempre por seguridad (regla del proyecto), aunque el resto sea provisorio.

**Diferido del producto (hasta que exista el CashFlowEngine + tablas `cash_flow_*`):** materialización de
`cash_flow_entries`, la rama soft-delete del DELETE, y el endpoint `POST /incomes/{id}/reactivate`. La
columna `deleted_at` se crea **ahora** igual, para no migrar la tabla después. Decisión de orden: slice
vertical de `incomes` primero (es el insumo del CashFlowEngine, que lee de esta tabla). `incomes` **no**
usa el ReviewEngine (Notion: "no tiene reviewer de subdominio… el motor corre directo tras el insert").

---

## 2. Alcance del slice 1

**Entra:** el modelo SQLAlchemy `Income`, la migración que crea la tabla `incomes`, y el registro del
modelo en `app/models/__init__.py` (para Alembic autogenerate y el `create_all` del harness de tests).

**No entra:** endpoints, schemas Pydantic, capa de servicio, validaciones de negocio, error codes. Sin
seed (es data de usuario, no un catálogo de admin).

---

## 3. Esquema de la tabla (fuente: Notion → BD → Ingresos → incomes)

| columna | tipo | null | notas |
|---|---|---|---|
| id | `uuid` PK, default `uuid4` | no | |
| user_id | `uuid` FK→`users.id` | no | a quién pertenece |
| income_type_id | `smallint` FK→`income_types.id` | no | |
| currency_id | `smallint` FK→`currencies.id` | no | |
| amount | `numeric(12,2)` | no | monto esperado, Decimal; la validación `> 0` es del slice 2 |
| description | `varchar(100)` | no | texto libre del usuario; el mínimo de 8 chars es del slice 2 |
| is_monthly_recurring | `boolean` | no | forma del ingreso (recurrente vs duración fija) |
| payment_day | `smallint` | sí | día de cobro 1–31 (forma recurrente) |
| first_income_date | `date` | sí | fecha del primer cobro (forma duración fija) |
| total_months | `smallint` | sí | cantidad de meses (forma duración fija) |
| shift_weekends | `boolean` | no | corrimiento de fin de semana |
| deleted_at | `timestamp(tz)` | sí | soft-delete reversible (documentado en Notion) |
| created_at | `timestamp(tz)` | no | `server_default now()` |
| updated_at | `timestamp(tz)` | no | `server_default now()`, `onupdate now()` |

Tipos SQLAlchemy concretos (patrón de `app/models/user.py`): `UUID(as_uuid=True)`, `SmallInteger`,
`Numeric(12, 2)`, `String(100)`, `Boolean`, `Date`, `DateTime(timezone=True)`, `func.now()`.

---

## 4. Decisiones, con su porqué

- **`deleted_at` desde el slice 1:** está en el esquema de Notion y el slice 2 (GET) deriva `is_deleted`
  de ella. Crearla ahora evita una migración posterior, aunque la rama que la setea (soft-delete) se
  difiera al CashFlowEngine. Segundo caso de soft-delete del proyecto (junto a `users`), todo dentro de
  la excepción "soft-delete solo donde se documente" del CLAUDE.md raíz.
- **Sin defaults en BD para los booleanos** (`is_monthly_recurring`, `shift_weekends`): los inserta el
  backend en el slice 2, igual que la regla acordada para `country_code` ("no quiero que en la tabla esté
  por defecto; que lo inserte el backend"). En BD son `NOT NULL` sin `server_default`.
- **Sin CHECK constraints:** las reglas de forma (modelo binario recurrente/duración fija), rango de
  `payment_day` (1–31), `total_months ≥ 1`, `amount > 0` y `description` ≥ 8 viven en la capa de servicio
  del slice 2, como define Notion ("validación en endpoints"). La tabla solo lleva FKs y `NOT NULL`.
- **`amount numeric(12,2)`:** convención de plata del proyecto (Decimal, nunca float).
- **FKs sin `ON DELETE` especial:** hard-delete por defecto del proyecto; el borrado en cascada de
  `cash_flow_entries` es asunto del subdominio del engine, no de esta tabla.

---

## 5. Verificación

- `alembic revision --autogenerate -m "incomes"` → revisar la migración generada (que cree las 3 FKs,
  los `NOT NULL` correctos y los nullables `payment_day`/`first_income_date`/`total_months`/`deleted_at`)
  → `alembic upgrade head` sobre `margin`.
- Chequeo por `psql -d margin`: columnas, tipos, nullability y las 3 foreign keys.
- **Test mínimo de round-trip** en `tests/test_incomes_model.py`: insertar un `Income` válido (con un
  `user`, `income_type` y `currency` sembrados en el test) y releerlo; confirmar que persiste, que los
  campos nullables aceptan NULL y que `created_at`/`updated_at` se completan solos. Regresión: `pytest -q`
  sigue verde.

---

## 6. Fuera de alcance (recordatorio explícito)

- **Slice 2** (`POST` + `PATCH`): schemas, capa de servicio, validación de forma (modelo binario), y los
  error codes `income_type_invalid`, `currency_not_available`, `description_invalid`, `amount_invalid`,
  `payment_day_invalid`, `recurring_income_requires_payment_day`, `fixed_term_income_requires_dates`,
  `total_months_invalid`, `income_form_inconsistent`, `not_found` (404 del PATCH).
- **Slice 3** (`GET` + `DELETE` provisorio): listado filtrado por `user_id` con `is_deleted` derivado;
  hard-delete simple (filtro por `user_id` + `not_found` 404), sin lógica de `cash_flow`/soft-delete.
- **Cuando exista el CashFlowEngine + tablas `cash_flow_*`:** reemplazar el `DELETE` provisorio por el
  completo (hard-delete + rama soft-delete según pagos reales + cascada de `cash_flow_entries`),
  materialización de `cash_flow_entries` en POST/PATCH, y `POST /incomes/{id}/reactivate`.

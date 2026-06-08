# Tabla `obligations` — Diseño

> Sub-proyecto #1 del subdominio **Obligaciones**. La entidad unificada donde viven gastos y deudas
> (`gasto` / `deuda` / `deuda_abierta`, según el `obligation_kind` del tipo asociado). Este slice crea
> **solo el modelo + la migración** (con las 4 columnas del ciclo de revisión y la autoreferencia); toda
> la lógica (motores, reviewer, endpoints, validación kind↔columnas) vive en slices posteriores. El *qué*
> está en Notion → BD → Obligaciones → `obligations`.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** `users`, `obligation_types`, `priority_levels`, `institutions`, `currencies` (todas ya en
  el repo). El enum `obligation_kind` ya existe (lo creó la migración de `obligation_types`).
- **Cierre:** rama `feat/obligations-tabla`, **squash-merge** a `main`.

---

## 1. Alcance

Crear la tabla `obligations`: modelo SQLAlchemy `app/models/obligation.py`, su registro en
`app/models/__init__.py`, la migración Alembic, y tests mínimos de inserción/constraints.

**Fuera de alcance:** `CashFlowEngine.expenses/debts/open_debts`, `ReviewEngine.obligations`, los endpoints
(`expenses`/`debts`/DELETE/acknowledge), la validación kind↔columnas y cualquier servicio. Son los slices
#2–#6.

---

## 2. Columnas

Espeja la spec de Notion. `numeric`/`Decimal` para plata y tasas (nunca float).

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | `default=uuid.uuid4` |
| `user_id` | uuid FK→users | No | A quién pertenece |
| `obligation_type_id` | smallint FK→obligation_types | No | Su `obligation_kind` define la sección |
| `priority_level` | smallint FK→priority_levels | No | Default heredado del tipo (lo setea el backend) |
| `institution_id` | smallint FK→institutions | Sí | Solo aplica a `deuda` |
| `description` | varchar(100) | Sí | Texto libre |
| `is_monthly_recurring` | boolean | No | Recurrente sin fin (solo gasto). Backend lo setea |
| `due_day` | smallint | Sí | Día de vencimiento 1–31 |
| `currency_id` | smallint FK→currencies | No | Moneda de la obligación |
| `amount` | numeric(12,2) | No | Monto de la cuota/compromiso |
| `total_installments` | smallint | Sí | Cuotas totales (solo deuda con cronograma) |
| `first_due_date` | date | Sí | Ancla del vencimiento (doble rol cuota/único) |
| `shift_weekends` | boolean | No | Corrimiento de finde. Backend lo setea |
| `financing_rate` | numeric(5,2) | Sí | % anual de financiación |
| `overdue_rate` | numeric(5,2) | Sí | % anual punitorio |
| `rates_add_vat` | boolean | No | Si a las tasas hay que sumarles IVA. Backend lo setea |
| `origin_obligation_id` | uuid FK→obligations | Sí | Autoreferencia (mora tipo `atraso`) |
| `is_closed` | boolean | No | Baja explícita del usuario. Backend lo setea |
| `reviewed_at` | timestamptz | Sí | Ciclo de revisión |
| `review_findings` | text | No | Ciclo de revisión. El backend setea `'[]'` al crear |
| `user_acknowledged_at` | timestamptz | Sí | Ciclo de revisión |
| `is_ready` | boolean | No | Ciclo de revisión. Backend lo setea |
| `created_at` | timestamptz | No | `server_default=now()` |
| `updated_at` | timestamptz | No | `server_default=now()`, `onupdate=now()` |

**No existe columna `obligation_kind`**: se deriva vía `obligation_type_id → obligation_types.obligation_kind`.

---

## 3. Decisiones, con su porqué

1. **Sin columna `obligation_kind`.** Una sola fuente de verdad (el tipo). Evita desincronización entre la
   obligación y su tipo.
2. **Booleans/text NOT NULL sin `server_default`; los asigna el backend.** Misma convención que
   `plan_movements`/`cash_flow_entries`: la columna es NOT NULL y el servicio siempre setea el valor
   (`is_monthly_recurring`, `is_closed`, `rates_add_vat`, `is_ready` → false; `review_findings` → `'[]'`).
   Forzar el set explícito es deliberado. (Los timestamps sí llevan `server_default=now()` + `onupdate`,
   como el resto de las tablas.)
3. **Sin CHECK constraints de nullabilidad por kind.** Las reglas "gasto no lleva tasas", "deuda_abierta
   todo NULL", "due_day solo en recurrente/cronograma", etc. son **invariantes del backend** (slices de
   motores/endpoints), no de la BD — igual que en `plan_movements`. La BD garantiza tipos y FKs; el
   servicio garantiza la coherencia kind↔columnas.
4. **`origin_obligation_id` autoref, sin ON DELETE cascade.** El hard-delete lo orquesta el backend con la
   regla "borrar hijas primero" (slice de endpoints). Todas las FKs quedan en RESTRICT por defecto (no se
   cascadea desde BD).
5. **Índices:** `user_id` (listado por usuario) y `origin_obligation_id` (check de hijas del hard-delete).
6. **`timestamptz`** (timestamp with time zone) para los 4 timestamps de fecha-hora (`reviewed_at`,
   `user_acknowledged_at`, `created_at`, `updated_at`), consistente con las demás tablas. `first_due_date`
   y `due_day` no son fecha-hora (date / smallint).

---

## 4. Modelo y migración

- `app/models/obligation.py`: clase `Obligation(Base)`, `__tablename__ = "obligations"`, columnas según §2
  con `Mapped`/`mapped_column`. FKs con `ForeignKey("tabla.col")`. La autoref usa
  `ForeignKey("obligations.id")`.
- Registrar en `app/models/__init__.py` (importar `Obligation`) para que Alembic la detecte.
- Migración: `alembic revision --autogenerate -m "create obligations"` → revisar → `alembic upgrade head`.
  Verificar que el autogenerate tome bien las FKs (incluida la autoref) y los índices; ajustar a mano si
  hace falta. El enum `obligation_kind` **no** se recrea (ya existe; la tabla no lo usa como columna).

---

## 5. Tests (`tests/test_obligations_model.py`)

Sembrando country UY + currency + priority_levels + obligation_types + un usuario. Sin endpoints (es slice
de tabla):

- Insertar una obligación **gasto** mínima (recurrente: `is_monthly_recurring=true`, `due_day`, sin tasas)
  y releerla; sus campos persisten.
- Insertar una **deuda** con cronograma (`total_installments`, `first_due_date`, `due_day`, tasas,
  `rates_add_vat`) y releerla.
- Insertar una **deuda_abierta** mínima (fechas/tasas en NULL) y releerla.
- FK inválida (`obligation_type_id` inexistente) → IntegrityError.
- Autoreferencia: crear una obligación con `origin_obligation_id` apuntando a otra existente; persiste.
- NOT NULL: insertar sin `amount` (o sin `review_findings`/`is_ready`) → IntegrityError.

> Nota: los tests arman el schema desde los modelos (`create_all`), no desde la migración; igual hay que
> sembrar las maestras (`priority_levels`, `obligation_types`) por las FKs. Reusar/extender las fixtures de
> `conftest`.

---

## 6. Plan de implementación (orientativo)

Un slice (`feat/obligations-tabla`), TDD:
1. `tests/test_obligations_model.py` (rojo) → `app/models/obligation.py` + registro en `__init__.py`
   (verde) → commit.
2. Migración autogenerada + revisada (`alembic upgrade head` corre limpio) → commit.
3. Suite completa verde → cierre.

# Tarjetas de crédito — Tablas (data model) — Diseño

> Primer sub-proyecto del subdominio **Tarjetas de crédito**: crear **solo las tablas** (modelos +
> migración + tests de constraints), en un único slice. Toda la lógica (endpoints de staging/promote, los
> reviewers `ReviewEngine.staging_credit_cards` y `ReviewEngine.credit_cards`, el `CashFlowEngine.credit_cards`
> con sus dos responsabilidades, el borrado híbrido, la herencia de tipo) vive en sub-proyectos posteriores.
> El *qué* de cada tabla está en Notion → BD → Tarjetas de crédito.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de** (todo ya en el repo): `users`, `institutions`, `currencies`, `countries`, y los dos
  catálogos del subdominio — `credit_card_networks` y `credit_card_item_types` — que **ya están creados,
  sembrados, registrados y expuestos en `/bootstrap`**. Los 7 `review_finding_codes` de tarjetas también
  están sembrados.
- **Cierre:** una rama (`feat/credit-cards-tablas`), **squash-merge** a `main` (1 commit).

---

## 1. Alcance

Crear las **6 tablas restantes** del subdominio, como modelos SQLAlchemy + una migración Alembic + registro
en `app/models/__init__.py` + tests de inserción/constraints. Nada de servicios, endpoints ni motores.

Dos árboles independientes, ambos colgando solo de catálogos que ya existen:

- **Definitivas:** `credit_cards` (eje) → `credit_card_statements` → `credit_card_statement_items`; más
  `credit_card_purchases` (cuelga de `credit_cards`).
- **Staging:** `staging_credit_cards` (madre) → `staging_credit_card_items`.

**Fuera de alcance:** endpoints `staging-credit-card-statements` y `credit-cards`, promoción, ambos reviewers,
el `CashFlowEngine.credit_cards`, el borrado híbrido soft/hard, la herencia de tipo (`credit_card_purchases`
como fuente de autocompletado), la exposición de las definitivas/staging en algún GET. Sub-proyectos
posteriores.

**Ya hecho (no rehacer):** `credit_card_networks`, `credit_card_item_types` (modelos, migraciones con seed,
`__init__`, schemas y servicio de `/bootstrap`), y el seed de `review_finding_codes`.

---

## 2. Un solo slice

Las 6 tablas son **schema puro** (sin lógica), así que van juntas en una rama `feat/credit-cards-tablas`:
6 modelos, **una** migración que crea las 6 en orden de dependencia, y **un test file por tabla**. Se
squash-mergea como **un commit**. El orden de creación (por las FKs) es:

| # | Tabla | Notas |
|---|---|---|
| 1 | `credit_cards` | Eje. 4 columnas del ciclo + `deleted_at` + índice único parcial. |
| 2 | `credit_card_statements` | UNIQUE de período; cuelga de `credit_cards`. |
| 3 | `credit_card_statement_items` | CASCADE off del statement. |
| 4 | `credit_card_purchases` | Autocompletado; cuelga de `credit_cards`. |
| 5 | `staging_credit_cards` | Madre con ciclo + `UNIQUE(user_id)`. Independiente de 1–4. |
| 6 | `staging_credit_card_items` | CASCADE off de la madre. |

Las tablas marcadas (3, 6) deben crearse después de su madre; el resto solo necesita los catálogos ya
existentes. La migración respeta este orden.

---

## 3. Columnas por tabla

`numeric`/`Decimal` para plata (12,2) y tasas (5,2), nunca float. Los 4 timestamps de fecha-hora
(`reviewed_at`, `user_acknowledged_at`, `created_at`, `updated_at`, y `deleted_at` donde aplica) son
`timestamptz`. `closing_date`, `due_date`, `charge_date`, `last_statement_closing_date` son `date`. PK uuid
con `default=uuid.uuid4`. `created_at`/`updated_at` llevan `server_default=now()` (+ `onupdate=now()` en
`updated_at`); las columnas de ciclo NOT NULL las setea el backend (igual que `obligations`).

### 3.1 `credit_cards` (slice 1)

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | |
| `user_id` | uuid FK→users | No | Dueño. Indexado |
| `institution_id` | smallint FK→institutions | No | Emisor |
| `card_network_id` | smallint FK→credit_card_networks | No | Red |
| `current_limit` | numeric(12,2) | No | Límite |
| `closing_day` | smallint | No | Día de cierre 1–31 (inferido al crear) |
| `financing_rate_local` | numeric(5,2) | No | Se conserva si el resumen no la trae |
| `overdue_rate_local` | numeric(5,2) | No | |
| `financing_rate_usd` | numeric(5,2) | No | |
| `overdue_rate_usd` | numeric(5,2) | No | |
| `rates_add_vat` | boolean | No | Mismo significado que en `obligations` |
| `reviewed_at` | timestamptz | Sí | Ciclo de revisión |
| `review_findings` | text | No | Ciclo. Backend setea `'[]'` al crear |
| `user_acknowledged_at` | timestamptz | Sí | Ciclo |
| `is_ready` | boolean | No | Ciclo. Backend lo setea |
| `created_at` | timestamptz | No | `server_default=now()` |
| `updated_at` | timestamptz | No | `server_default=now()`, `onupdate=now()` |
| `deleted_at` | timestamptz | Sí | Soft-delete; NULL = vigente |

**Índice único parcial:** `UNIQUE (user_id, institution_id, card_network_id) WHERE deleted_at IS NULL`
(una soft-deleted no bloquea recrear la combinación).

### 3.2 `credit_card_statements` (slice 2)

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | |
| `credit_card_id` | uuid FK→credit_cards | No | Tarjeta dueña |
| `issue_year` | smallint | No | Año del período |
| `issue_month` | smallint | No | Mes 1–12 |
| `closing_date` | date | No | |
| `due_date` | date | No | |
| `total_local` | numeric(12,2) | No | |
| `total_usd` | numeric(12,2) | No | |
| `minimum_payment_local` | numeric(12,2) | No | |
| `minimum_payment_usd` | numeric(12,2) | No | |
| `created_at` | timestamptz | No | |
| `updated_at` | timestamptz | No | |

**UNIQUE (credit_card_id, issue_month, issue_year)** — un resumen por período y tarjeta.

### 3.3 `credit_card_statement_items` (slice 2)

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | |
| `credit_card_statement_id` | uuid FK→credit_card_statements | No | **ON DELETE CASCADE** |
| `charge_date` | date | No | |
| `description` | text | No | |
| `amount` | numeric(12,2) | No | En la unidad de `currency_id` |
| `currency_id` | smallint FK→currencies | No | |
| `current_installment` | smallint | Sí | Ambas-o-ninguna con `total_installments` |
| `total_installments` | smallint | Sí | |
| `item_type_id` | smallint FK→credit_card_item_types | No | compra/interés/suscripción |
| `created_at` | timestamptz | No | |
| `updated_at` | timestamptz | No | |

### 3.4 `credit_card_purchases` (slice 3)

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | |
| `credit_card_id` | uuid FK→credit_cards | No | Tarjeta |
| `description` | text | No | |
| `charge_date` | date | No | Fecha real del cargo |
| `amount` | numeric(12,2) | No | Valor de **cada cuota**, no el total |
| `currency_id` | smallint FK→currencies | No | |
| `total_installments` | smallint | Sí | NULL si fue un solo pago. No se persiste la cuota actual (se deriva) |
| `item_type_id` | smallint FK→credit_card_item_types | No | |
| `last_statement_closing_date` | date | No | `closing_date` del último resumen donde apareció |
| `created_at` | timestamptz | No | |
| `updated_at` | timestamptz | No | |

### 3.5 `staging_credit_cards` (slice 4)

Misma forma que `credit_cards` para datos de tarjeta, **más** datos del resumen puntual, **todo nullable
salvo el ciclo** (la madre entra como venga; el usuario completa antes de promover).

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | |
| `user_id` | uuid FK→users | No | **UNIQUE** — un staging por usuario |
| `institution_id` | smallint FK→institutions | Sí | Resuelto contra catálogo; NULL si no resuelve |
| `card_network_id` | smallint FK→credit_card_networks | Sí | Ídem |
| `closing_date` | date | Sí | |
| `due_date` | date | Sí | |
| `current_limit` | numeric(12,2) | Sí | |
| `total_local` | numeric(12,2) | Sí | |
| `total_usd` | numeric(12,2) | Sí | |
| `minimum_payment_local` | numeric(12,2) | Sí | |
| `minimum_payment_usd` | numeric(12,2) | Sí | |
| `financing_rate_local` | numeric(5,2) | Sí | Las 4 tasas pueden quedar NULL legítimamente |
| `overdue_rate_local` | numeric(5,2) | Sí | |
| `financing_rate_usd` | numeric(5,2) | Sí | |
| `overdue_rate_usd` | numeric(5,2) | Sí | |
| `rates_add_vat` | boolean | Sí | `= NOT vat_excluded` (lo resuelve el endpoint, no esta tabla) |
| `reviewed_at` | timestamptz | Sí | Ciclo |
| `review_findings` | text | No | Ciclo. Default `'[]'` |
| `user_acknowledged_at` | timestamptz | Sí | Ciclo |
| `is_ready` | boolean | No | Ciclo |
| `created_at` | timestamptz | No | |
| `updated_at` | timestamptz | No | |

### 3.6 `staging_credit_card_items` (slice 4)

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `id` | uuid PK | No | |
| `staging_credit_card_id` | uuid FK→staging_credit_cards | No | **ON DELETE CASCADE** |
| `charge_date` | date | Sí | Entra como venga; el usuario completa |
| `description` | text | Sí | |
| `amount` | numeric(12,2) | Sí | |
| `currency_id` | smallint FK→currencies | Sí | |
| `current_installment` | smallint | Sí | |
| `total_installments` | smallint | Sí | |
| `item_type_id` | smallint FK→credit_card_item_types | Sí | No viene en el resumen: NULL al cargar |
| `created_at` | timestamptz | No | |
| `updated_at` | timestamptz | No | |

---

## 4. Decisiones, con su porqué

1. **Índice único parcial en `credit_cards`.** `UNIQUE (user_id, institution_id, card_network_id) WHERE
   deleted_at IS NULL`. Es un índice parcial de Postgres (`postgresql_where`), no un `UniqueConstraint`, para
   que una tarjeta soft-deleted no bloquee volver a tener esa combinación. Se escribe a mano si el
   autogenerate no lo toma con el `WHERE`.
2. **Ciclo de revisión NOT NULL sin `server_default`; lo setea el backend.** Misma convención que
   `obligations`: `review_findings` y `is_ready` son NOT NULL y el servicio siempre los asigna (`'[]'` /
   `false` al crear). `reviewed_at` y `user_acknowledged_at` son nullable. (Vale para `credit_cards` y
   `staging_credit_cards`; las demás tablas no llevan ciclo.)
3. **`created_at == updated_at` al crear `credit_cards`.** El `ReviewEngine.credit_cards` distingue "recién
   creada" de "editada" comparando ambos. A nivel tabla alcanza con el patrón estándar (`server_default=now()`
   en los dos, `onupdate=now()` solo en `updated_at`): en el INSERT ambos toman el mismo `now()`. La garantía
   fina (que la promoción no toque `updated_at` antes del reviewer) es del sub-proyecto del endpoint, no de la
   tabla.
4. **`ON DELETE CASCADE` en los dos `*_items`.** Los ítems pertenecen a su madre (statement / staging) y se
   van con ella. Se declara en la FK (`ForeignKey(..., ondelete="CASCADE")`).
5. **Sin CHECK de "ambas-o-ninguna" para las cuotas, ni de completitud del staging.** Son invariantes del
   backend (validación al promover / al editar ítem), no de la BD — igual que la coherencia kind↔columnas en
   `obligations`. La BD garantiza tipos, FKs y los UNIQUE/índices declarados.
6. **`UNIQUE (user_id)` en `staging_credit_cards`.** Un solo estado de cuenta en revisión por usuario; el
   UPSERT del endpoint de carga reconcilia contra esa única fila. Constraint a nivel BD.
7. **`UNIQUE (credit_card_id, issue_month, issue_year)` en statements.** Un resumen por período; red de
   seguridad bajo el error amigable `statement_period_exists` que dará el endpoint de promote.
8. **Todas las FKs en RESTRICT por defecto, salvo los dos CASCADE de `*_items`.** El borrado híbrido de
   `credit_cards` (soft/hard, orquestado) es de un sub-proyecto posterior; la tabla no cascadea desde BD más
   allá de los ítems.
9. **`credit_card_purchases` no persiste la cuota actual.** Solo `total_installments` + `charge_date`; la
   cuota vigente se deriva (regla del proyecto: no persistir lo derivable).

---

## 5. Modelo y migración

- Un archivo de modelo por tabla en `app/models/` (`credit_card.py`, `credit_card_statement.py`,
  `credit_card_statement_item.py`, `credit_card_purchase.py`, `staging_credit_card.py`,
  `staging_credit_card_item.py`), clase `Base`, columnas según §3 con `Mapped`/`mapped_column`.
- Registrar cada clase en `app/models/__init__.py` (en orden de dependencia) para que Alembic la detecte.
- Una migración: `alembic revision --autogenerate -m "create credit card tables"` → **revisar** (FKs, los dos
  CASCADE, UNIQUE, y en especial el índice parcial con `WHERE deleted_at IS NULL`, que suele requerir ajuste
  manual con `op.create_index(..., postgresql_where=...)`) → `alembic upgrade head`.

---

## 6. Tests (un file por tabla, `tests/test_<tabla>_model.py`)

Sembrando lo necesario por las FKs (country UY + institutions + currencies + los dos catálogos CC + un
usuario; reusar/extender fixtures de `conftest`). Sin endpoints:

- **`credit_cards`:** insertar una tarjeta completa y releerla; el índice único parcial rechaza una segunda
  vigente con misma `(user_id, institution_id, card_network_id)`; **permite** crear una nueva si la anterior
  tiene `deleted_at` con valor; FK inválida → IntegrityError; NOT NULL (sin `review_findings`/`is_ready`/una
  tasa) → IntegrityError.
- **`credit_card_statements`:** insertar un statement y releerlo; el UNIQUE `(credit_card_id, issue_month,
  issue_year)` rechaza un duplicado de período.
- **`credit_card_statement_items`:** insertar un ítem colgando del statement; **borrar el statement borra sus
  ítems** (CASCADE); ítem en cuotas (ambas con valor) y de un pago (ambas NULL) persisten.
- **`credit_card_purchases`:** insertar una compra en cuotas y una de un pago (`total_installments` NULL) y
  releerlas; FK inválida → IntegrityError.
- **`staging_credit_cards`:** insertar una madre **mínima** (casi todo NULL, solo ciclo y user) y releerla;
  el `UNIQUE (user_id)` rechaza una segunda madre del mismo usuario.
- **`staging_credit_card_items`:** insertar un ítem incompleto (columnas NULL); **borrar la madre borra sus
  ítems** (CASCADE).

> Los tests arman el schema desde los modelos (`create_all`); igual hay que sembrar las maestras por las FKs.
> El CASCADE exige que la FK tenga `ondelete="CASCADE"` y que el borrado de la madre pase por la BD (no solo
> el ORM); en SQLite/Postgres de tests, emitir el `DELETE` y `flush`/`commit` y verificar que el hijo no esté.

---

## 7. Plan de implementación (orientativo)

Un slice (`feat/credit-cards-tablas`), TDD tabla por tabla, una migración, squash-merge a `main`:

1. Por cada tabla (en el orden de §2): test file (rojo) → modelo + registro en `__init__.py` (verde).
2. Una migración autogenerada con las 6 tablas → **revisar** (FKs, los dos CASCADE, los UNIQUE, y el índice
   parcial `WHERE deleted_at IS NULL` ajustado a mano) → `alembic upgrade head` corre limpio.
3. Suite completa verde → cierre.

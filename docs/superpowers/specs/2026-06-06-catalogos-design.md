# Catálogos (credit_card_networks, credit_card_item_types, obligation_types, income_types) — Diseño

> Crea las 4 tablas de catálogo restantes (administradas por el admin) para destrabar las features que
> las referencian (obligations, incomes, tarjetas de crédito). El *qué* de cada tabla vive en Notion → BD.
> Última tanda de catálogos de este estilo.

- **Fecha:** 2026-06-06
- **Estado:** aprobado para implementar
- **Depende de:** `countries` y `priority_levels` (ya en `main`).
- **Estrategia:** un PR (`feat/catalog-tables`), un commit chico por tabla, **squash-merge** a un commit en `main`.

---

## 1. Alcance

- 4 modelos SQLAlchemy + migraciones Alembic con seeds: `credit_card_networks`, `credit_card_item_types`, `obligation_types`, `income_types`.
- Registrar cada modelo en `app/models/__init__.py`.
- `obligation_types` crea además el **enum nativo `obligation_kind`** (`CREATE TYPE`), patrón ya usado en `auth_provider`.
- **Sin endpoints** (se sirven por `GET /bootstrap` a futuro). **Sin tests nuevos**: se verifica esquema + seeds por `psql` + regresión `pytest`.

---

## 2. Dependencias

Todas referencian tablas que **ya existen**; no se referencian entre sí (sin orden interno obligatorio):
- `credit_card_networks.country_code` → `countries`.
- `obligation_types.default_priority_level` → `priority_levels`.
- `credit_card_item_types`, `income_types`: independientes.

---

## 3. Tablas (fuente: Notion)

### credit_card_networks
| columna | tipo | null | notas |
|---|---|---|---|
| id | smallint PK | no | id fijo |
| country_code | varchar(2) FK→countries | no | |
| code | varchar(20) | no | minúscula, sin espacios (ej. `amex`) |
| name | varchar(50) | no | visible (ej. "Amex") |

**UNIQUE (country_code, code).** **Seed (UY):** (visa, Visa), (mastercard, Mastercard), (amex, Amex), (oca, OCA), (diners, Diners), (cabal, Cabal) — 6 filas, ids 1–6.

### credit_card_item_types
| columna | tipo | null | notas |
|---|---|---|---|
| id | smallint PK | no | id fijo |
| code | varchar(20) | no | UNIQUE (ej. `compra`) |
| name | varchar(50) | no | visible |
| description | varchar(200) | no | |

Sin `country_code` (catálogo global). **Seed:** ids 1–3 — `compra`/Compra, `interes`/Interés, `suscripcion`/Suscripción (descripciones exactas de Notion).

### obligation_types
| columna | tipo | null | notas |
|---|---|---|---|
| id | smallint PK | no | id fijo |
| obligation_kind | enum `obligation_kind` | no | `gasto`/`deuda`/`deuda_abierta` |
| code | varchar(20) | no | UNIQUE |
| name | varchar(50) | no | visible |
| description | varchar(200) | no | |
| default_priority_level | smallint FK→priority_levels | no | prioridad heredada |
| visible | boolean | no | default true |

**Enum:** `CREATE TYPE obligation_kind AS ENUM ('gasto', 'deuda', 'deuda_abierta')`. Valores en inglés técnico del dominio (excepción consciente, igual que `auth_provider`; aquí son términos del negocio en español del modelo — se mantienen tal cual los define Notion).

**Seed (10 filas, ids 1–10):**
| id | kind | code | name | default_priority_level |
|---|---|---|---|---|
| 1 | gasto | alquiler | Alquiler / hipoteca | 2 |
| 2 | gasto | utilities | Servicios básicos | 2 |
| 3 | gasto | salud | Salud | 2 |
| 4 | gasto | subscriptions | Suscripciones | 6 |
| 5 | gasto | otros_gastos | Otros gastos | 6 |
| 6 | deuda | adelanto_sueldo | Adelanto de sueldo | 1 |
| 7 | deuda | atraso | Atraso u obligación | 3 |
| 8 | deuda_abierta | informal | Deuda informal | 5 |
| 9 | deuda | otras_deudas | Otra deuda | 5 |
| 10 | deuda | prestamo | Préstamo en cuotas | 5 |

(Descripciones exactas de Notion en el seed.)

### income_types
| columna | tipo | null | notas |
|---|---|---|---|
| id | smallint PK | no | id fijo |
| code | varchar(20) | no | UNIQUE |
| name | varchar(50) | no | visible |
| visible | boolean | no | default true |

**Seed (9 filas, ids 1–9):** sueldo/Sueldo, pension/Pensión · jubilación, alquiler/Alquiler que cobra, freelance/Freelance, comisiones/Comisiones, horas_extra/Horas extra, aguinaldo/Aguinaldo, devolucion_impuestos/Devolución de impuestos, otro/Otro.

---

## 4. Convenciones aplicadas

- Tablas/columnas en inglés `snake_case`; textos visibles (`name`, `description`) en español.
- Ids fijos (`autoincrement=False`); vienen del seed.
- `visible` (boolean default true) en `obligation_types` e `income_types`.
- Enum nativo solo en `obligation_types` (`obligation_kind`); la migración lo crea y el downgrade lo dropea.
- `code` como identificador estable interno; UNIQUE donde Notion lo indica.
- Seeds vía `op.bulk_insert` en la migración.

---

## 5. Verificación

Tras `alembic upgrade head`, por `psql` contra `margin`:
- `credit_card_networks`: 6 filas; UNIQUE(country_code, code) creado.
- `credit_card_item_types`: 3 filas.
- `obligation_types`: 10 filas; enum `obligation_kind` con 3 labels; FK a priority_levels válida.
- `income_types`: 9 filas.
- Regresión: `pytest -q` sigue verde (los modelos nuevos no rompen el harness).

---

## 6. Decisiones, con su porqué

- **Un PR para las 4:** misma familia (catálogos de admin), homogéneas, bajo riesgo. Squash a un commit.
- **Sin endpoints:** YAGNI; se sirven por `GET /bootstrap`. Objetivo: destrabar FKs (obligations, incomes, tarjetas).
- **`obligation_kind` como enum nativo (no tabla):** Notion lo modela así — garantiza a nivel BD valores válidos y crece sumando un valor al enum sin migración de esquema. Mismo criterio que `auth_provider`.
- **Ids fijos en catálogos:** referencias estables y reproducibles entre entornos.

# Tablas maestras — Diseño

> Crea las tablas maestras restantes (catálogos administrados por el admin) para destrabar las
> features que las referencian (incomes, obligations, plans, etc.). El *qué* de cada tabla vive en
> Notion → BD → Tablas maestras. `countries` ya existe; este spec cubre las 5 que faltan.

- **Fecha:** 2026-06-06
- **Estado:** aprobado para implementar
- **Depende de:** `countries` (ya en `main`).
- **Estrategia:** un solo PR (`feat/master-tables`), un commit chico por tabla en la rama, **squash-merge** a un commit en `main`.

---

## 1. Alcance

- Crear **5 modelos SQLAlchemy + 1 migración Alembic con sus seeds**: `currencies`, `currency_rates`, `priority_levels`, `institutions`, `review_finding_codes`.
- Registrar cada modelo en `app/models/__init__.py` (para que Alembic los vea).
- **Sin endpoints.** Los catálogos se sirven después por `GET /bootstrap` (regla de GLOBAL); ahora solo se necesita que las tablas + seeds existan para las FKs aguas abajo.
- **Sin tests automatizados nuevos:** no hay endpoints ni lógica; se verifica esquema + seeds por `psql` (igual que se hizo con `countries`).

---

## 2. Dependencias y orden

```
countries (✓)
 ├── currencies            → currency_rates   (currency_rates depende de currencies)
 └── institutions
priority_levels            (independiente)
review_finding_codes       (independiente)
```

La migración crea las tablas en orden válido de FK: `currencies` antes de `currency_rates`; `currencies` e `institutions` después de `countries` (ya existe). `priority_levels` y `review_finding_codes` en cualquier punto.

---

## 3. Tablas (fuente: Notion)

### currencies
| columna | tipo | null | notas |
|---|---|---|---|
| id | smallint PK | no | identificador propio (no autoincremental: ids fijos del seed) |
| country_code | varchar(2) FK→countries | no | |
| name | varchar(40) | no | "Peso", "Dólar", … |
| is_legal_tender | boolean | no | default false; true solo para la moneda de curso legal |
| allowed_in_credit_card | boolean | no | default false |

**Seed (UY):** (1, Peso, legal=t, cc=t), (2, Dólar compra, f, f), (3, Dólar, f, t), (4, Unidad Indexada, f, f), (5, Unidad Reajustable, f, f).

### currency_rates
| columna | tipo | null | notas |
|---|---|---|---|
| currency_id | smallint FK→currencies | no | parte de PK compuesta |
| rate_date | date | no | parte de PK compuesta |
| value | numeric(14,6) | no | 1 unidad en moneda legal |
| is_projected | boolean | no | false=real, true=proyección |

**PK compuesta** (`currency_id`, `rate_date`). **Sin seed** (lo llena el backend).

### priority_levels
| columna | tipo | null | notas |
|---|---|---|---|
| level | smallint PK | no | 1–6 (1 = más urgente) |
| name | varchar(50) | no | etiqueta corta |
| description | varchar(200) | no | texto en 2ª persona |

**Seed:** 6 filas (1 Ineludible … 6 Ajustable) — textos exactos de Notion.

### institutions
| columna | tipo | null | notas |
|---|---|---|---|
| id | smallint PK | no | ids fijos del seed |
| country_code | varchar(2) FK→countries | no | |
| name | varchar(80) | no | "BROU", "Itaú", … |
| visible | boolean | no | default true |

**Seed (UY):** 1 BROU, 2 Itaú, 3 Santander, 4 Scotiabank, 5 OCA (todas visible=true).

### review_finding_codes
| columna | tipo | null | notas |
|---|---|---|---|
| code | varchar(50) PK | no | snake_case, estable (contrato) |
| message | varchar(200) | no | texto para el usuario, sin variables |

**Seed:** 10 codes con su message (exactos de Notion: `amount_above_threshold`, `overdue_lower_than_financing`, `rate_above_threshold`, `rates_not_updated`, `closing_after_due`, `due_date_in_future`, `due_date_too_old`, `new_card`, `closing_day_inferred`, `closing_day_changed`).

> `review_findings` (en obligations/incomes) referencia estos codes **lógicamente por JSON, sin FK reforzable**. No se modela FK acá.

---

## 4. Convenciones aplicadas

- Tablas/columnas en inglés `snake_case`; textos visibles (`name`, `description`, `message`) en español.
- `value` de `currency_rates` en `numeric(14,6)` (plata/tasas nunca float → `Decimal`).
- `visible` (boolean default true) es columna transversal de catálogos administrables (countries, institutions).
- Sin enums nativos en estas tablas.
- Seeds vía `op.bulk_insert` en la migración (versionados; el admin los mantiene por migración).
- Ids de `currencies`/`institutions` son **fijos** (vienen del seed), no autoincrementales — el resto del modelo referencia esos ids estables.

---

## 5. Verificación

Por cada tabla, tras `alembic upgrade head`, verificar esquema + seed con `psql` contra `margin`:
- `currencies`: 5 filas, `is_legal_tender=t` solo en id 1.
- `priority_levels`: 6 filas (1–6).
- `institutions`: 5 filas, todas `visible=t`.
- `review_finding_codes`: 10 filas.
- `currency_rates`: tabla creada, 0 filas (sin seed), PK compuesta.

---

## 6. Decisiones, con su porqué

- **Un PR para las 5:** son una unidad cohesiva (catálogos maestros), homogéneas y de bajo riesgo; 5 PRs sería ceremonia sin beneficio. Squash a un commit en `main`.
- **Sin endpoints ahora:** YAGNI; se sirven por `GET /bootstrap` cuando el frontend lo necesite. El objetivo es destrabar las FKs.
- **Ids fijos en catálogos:** los seeds usan ids explícitos para que las referencias (y futuros datos) sean estables y reproducibles entre entornos.
- **Sin FK en review_finding_codes:** la relación es por JSON (`review_findings`), no una columna FK; el backend valida integridad al insertar findings.

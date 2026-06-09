# currencies — metadata de display — Diseño

> Enriquecer el catálogo de monedas con dos atributos de **presentación** (`symbol` y `display_decimals`)
> para que la app/web renderice montos correctamente (`$ 1.000`, `U$S 50,00`) en vez de etiquetas tipo
> "Monto Peso" / "Monto Dólar". El backend solo persiste y expone; **el formateo es del cliente**.

- **Fecha:** 2026-06-09
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice: 2 columnas en `currencies` + migración + exposición en el catálogo.
- **Cierre:** rama `feat/currency-display-metadata`, **squash-merge** a `main`.
- **Fuera de alcance:** la web/app que consume el símbolo; cualquier cambio al storage de montos.

---

## 1. Decisión de fondo

Ambos atributos son **intrínsecos a cada moneda** y la relación es 1:1 → son **columnas en `currencies`**,
no una tabla aparte. `display_decimals` es **solo display**: el storage de montos sigue siendo
`numeric(12,2)` siempre (regla de plata intacta); la web redondea/formatea al mostrar.

---

## 2. Columnas nuevas en `currencies`

| Columna | Tipo | NULL | Default | Para qué |
|---|---|---|---|---|
| `symbol` | `varchar(10)` | No | `server_default=""` | símbolo a anteponer al monto |
| `display_decimals` | `smallint` | No | `server_default="2"` | decimales a mostrar (no afecta storage) |

- `NOT NULL` con default tolerante: una moneda futura insertada sin estos campos no rompe
  (`symbol=""`, `display_decimals=2`, el caso más común).
- `varchar(10)` sobra para `$`, `U$S`, `UI`, `UR`. **Sin** unicidad de símbolo (Dólar compra y Dólar
  comparten `U$S` a propósito).

**Modelo** (`app/models/currency.py`): agregar ambos `mapped_column` (mismo patrón que las columnas
booleanas existentes, que ya usan `server_default`).

---

## 3. Backfill de las 5 monedas UY (en la migración)

| id | name | symbol | display_decimals |
|---|---|---|---|
| 1 | Peso | `$` | 0 |
| 2 | Dólar compra | `U$S` | 2 |
| 3 | Dólar | `U$S` | 2 |
| 4 | Unidad Indexada | `UI` | 2 |
| 5 | Unidad Reajustable | `UR` | 2 |

---

## 4. Migración (Alembic, autogenerada + revisada)

- `upgrade`: `add_column` × 2 con sus `server_default`; luego `UPDATE` por `id` para backfillear las 5 filas.
- `downgrade`: `drop_column` × 2.
- Migración aditiva normal (`alembic upgrade head`), **sin recrear** la DB.

---

## 5. Exposición a la UI

`CurrencyOut` (`app/schemas/bootstrap.py`): agregar `symbol: str` y `display_decimals: int`. Salen solos en
el catálogo del `bootstrap` por `from_attributes`. No hay endpoint nuevo.

---

## 6. Archivos

| Archivo | Cambio |
|---|---|
| `app/models/currency.py` | + columnas `symbol`, `display_decimals` |
| `alembic/versions/<rev>_currencies_display_metadata.py` | add_column × 2 + UPDATE de backfill |
| `app/schemas/bootstrap.py` | + `symbol`, `display_decimals` en `CurrencyOut` |

---

## 7. Tests (TDD)

Postgres `margin_test` (`create_all` + savepoint). Las fixtures que construyen `Currency(...)` sin estos
campos siguen funcionando (el `server_default` cubre la inserción).

- **`tests/test_bootstrap.py`**: la fixture siembra el Peso con `symbol="$"` y `display_decimals=0`
  (explícito: los tests usan `create_all` + fixtures, **no** corren la migración, así que el `server_default`
  daría `""`/`2` — los valores reales hay que pasarlos al construir el `Currency`). El test assertea que el
  catálogo de monedas expone ambos campos y que el Peso trae `symbol="$"` y `display_decimals=0`.

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/currency-display-metadata`), TDD: test de bootstrap (rojo) → columnas en el modelo +
migración con backfill → `CurrencyOut` → suite verde → cierre. Notion: actualizar `BD → currencies` con las
dos columnas nuevas.

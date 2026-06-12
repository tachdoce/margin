# Actualizar cotizaciones desde CSV mensual

Fecha: 2026-06-12
Estado: aprobado (diseño)

## Problema

Las cotizaciones de monedas (`currency_rates`) hoy se siembran en la migración
`44c310780edb` con valores planos y poco realistas: un único valor por moneda
repetido todos los días desde 2026-04-01 hasta 2027-12-31
(`{2: 39, 3: 41, 4: 6.55, 5: 1921.36}`).

Tenemos una proyección mensual nueva (archivo
`proyeccion_indicadores_2026_2027.csv`) con una cotización por mes para cada
moneda, de 2026-06 a 2027-12. Queremos cargar esos valores, manteniendo la
regla de negocio de que **todos los días de un mes comparten la misma
cotización**.

## Decisiones tomadas (brainstorming)

- **Disparador:** migración Alembic versionada (no API ni servicio CRUD). Las
  cotizaciones siguen siendo datos maestros cargados en migraciones.
- **Granularidad:** se mantiene el schema por día (`currency_rates` con PK
  `(currency_id, rate_date)`). El valor mensual se **expande a todos los días**
  del mes. No se cambia el modelo ni el consumidor.
- **Alcance temporal:** se actualiza solo el rango del CSV (**2026-06 a
  2027-12**). Los meses 2026-04 y 2026-05 (fuera del CSV) quedan **intactos**
  con sus valores actuales.
- **Mecanismo:** delete-range + `bulk_insert` (opción A).
- **`is_projected`:** se mantiene en `True` para todo el rango (el archivo es
  una proyección de indicadores).

## Mapeo de columnas

El CSV trae las columnas `dolar compra, dolar venta, UI, UR`. Peso (id 1) no
lleva fila: el consumidor usa `COALESCE(value, 1)`.

| Columna CSV   | currency_id | Moneda           |
|---------------|-------------|------------------|
| dolar compra  | 2           | Dólar compra     |
| dolar venta   | 3           | Dólar            |
| UI            | 4           | Unidad Indexada  |
| UR            | 5           | Unidad Reajustable |

## Valores a cargar (CSV embebido)

La migración no lee archivos externos: los valores se embeben como literal
Python en su cuerpo. Mapeados a `{currency_id: valor}`:

| mes      | 2 (compra) | 3 (venta) | 4 (UI) | 5 (UR)   |
|----------|------------|-----------|--------|----------|
| 2026-06  | 40.40      | 41.40     | 6.57   | 1921.36  |
| 2026-07  | 40.42      | 41.42     | 6.60   | 1932.97  |
| 2026-08  | 40.44      | 41.44     | 6.62   | 1944.66  |
| 2026-09  | 40.46      | 41.46     | 6.65   | 1956.41  |
| 2026-10  | 40.48      | 41.48     | 6.67   | 1968.24  |
| 2026-11  | 40.49      | 41.49     | 6.70   | 1980.14  |
| 2026-12  | 40.50      | 41.50     | 6.72   | 1992.11  |
| 2027-01  | 40.61      | 41.61     | 6.75   | 2004.15  |
| 2027-02  | 40.71      | 41.71     | 6.77   | 2016.27  |
| 2027-03  | 40.82      | 41.82     | 6.80   | 2028.45  |
| 2027-04  | 40.93      | 41.93     | 6.83   | 2040.72  |
| 2027-05  | 41.03      | 42.03     | 6.85   | 2053.05  |
| 2027-06  | 41.14      | 42.14     | 6.88   | 2065.46  |
| 2027-07  | 41.25      | 42.25     | 6.91   | 2077.95  |
| 2027-08  | 41.36      | 42.36     | 6.93   | 2090.51  |
| 2027-09  | 41.47      | 42.47     | 6.96   | 2103.15  |
| 2027-10  | 41.58      | 42.58     | 6.98   | 2115.86  |
| 2027-11  | 41.69      | 42.69     | 7.01   | 2128.65  |
| 2027-12  | 41.80      | 42.80     | 7.04   | 2141.52  |

Todos los montos como `Decimal` (string en el literal), nunca `float`.

## Diseño de la migración

Nueva migración Alembic de **solo datos** (sin cambios de schema),
`down_revision` = head actual.

### `upgrade()`

1. `DELETE FROM currency_rates WHERE rate_date BETWEEN '2026-06-01' AND
   '2027-12-31'` (borra el rango del CSV; deja 2026-04 y 2026-05 intactos).
2. Recorrer cada mes del literal; para cada día del mes y cada `currency_id`,
   armar una fila `{currency_id, rate_date, value=Decimal(...),
   is_projected=True}`.
3. `op.bulk_insert(table, rows)`.

El último día de cada mes se calcula recorriendo días hasta cambiar de mes (sin
`float`, sin dependencias externas).

### `downgrade()`

Reversible: borra el mismo rango `2026-06-01 → 2027-12-31` y reinserta los
valores planos previos (`{2: "39", 3: "41", 4: "6.55", 5: "1921.36"}`)
expandidos a todos los días, con `is_projected=True`. Deja el rango idéntico al
estado anterior a esta migración.

## Impacto en consumidores

Ninguno estructural. `cash_flow_entry_service` sigue joineando por
`(currency_id, rate_date)` y la función `_rate()` sigue buscando igual. Solo
cambian los valores devueltos para fechas en 2026-06 → 2027-12.

## Verificación (manual)

**Por qué no hay test automatizado:** el harness de tests arma la base con
`Base.metadata.create_all()` (ver `tests/conftest.py:18`) y siembra datos a mano
con fixtures; **no corre las migraciones**. Por lo tanto los datos sembrados por
una migración no existen en los tests y no se pueden assertear ahí. Igual que el
seed original (`44c310780edb`), esta migración no lleva test automatizado.

La verificación es manual sobre la base dev (`margin`), tras `alembic upgrade
head`, con queries de spot-check:

1. **Valor puntual:** `SELECT value FROM currency_rates WHERE currency_id=3 AND
   rate_date='2026-06-15'` → `41.40`; e `id=4 / 2027-12-01` → `7.04`.
2. **Uniformidad mensual:** `SELECT COUNT(DISTINCT value) FROM currency_rates
   WHERE currency_id=2 AND rate_date BETWEEN '2027-03-01' AND '2027-03-31'` → `1`.
3. **Cambio entre meses:** `id=2 / 2026-06-15` (`40.40`) ≠ `id=2 / 2026-07-15`
   (`40.42`).
4. **Meses fuera del CSV intactos:** `id=3 / 2026-05-15` → `41` (sin cambios).
5. **Peso sin fila:** no hay `currency_id=1` en el rango.
6. **Reversibilidad:** `alembic downgrade -1` deja el rango en los valores planos
   previos (`id=3 / 2026-06-15` → `41`); `alembic upgrade head` lo vuelve a dejar
   con el CSV.

## Fuera de alcance (YAGNI)

- Endpoint / API de carga de cotizaciones.
- Servicio CRUD o pantalla de administración.
- Cambiar la granularidad de la tabla a por-mes.
- Cotizaciones reales (no proyectadas) o histórico previo a 2026-06.

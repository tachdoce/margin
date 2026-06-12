# Tipos `deuda` y `tarjetazo` en plan_movements

Fecha: 2026-06-12
Estado: aprobado (diseño)

## Problema

Hoy `plan_movements.kind` admite 3 valores (`ingreso`, `deuda_informal`,
`prestamo`). Falta poder registrar una **deuda en cuotas que no implica entrada
de capital**: el usuario ya tiene (o asume) una deuda y solo quiere proyectar
sus pagos, sin el ingreso de plata que sí genera un Préstamo.

Se agregan **dos** kinds nuevos. **Se comportan y se materializan igual** (deuda
en cuotas sin entrada de capital); la diferencia está en **cómo se crean**:

- `deuda` — el usuario carga las cuotas y tasas a mano, por el endpoint genérico.
- `tarjetazo` — se crea por un endpoint dedicado a partir de una tarjeta de
  crédito; el backend deriva tasas y fecha del primer pago. Ver Motivación.

## Motivación de `tarjetazo`

`tarjetazo` representa una **deuda de impulso** —una compra con tarjeta— que el
usuario agrega a un plan para **evaluar su impacto en el flujo de caja antes de
asumirla**. Se crea desde una tarjeta de crédito (el backend copia las tasas y
calcula cuándo caería el primer pago según el cierre/vencimiento), pero **no
queda vinculado a la tarjeta**: es un snapshot. Se modela como un kind aparte
para poder revisar estos movimientos tentativos y **borrarlos en bloque** sin
tocar el resto del plan.

Caso de uso en el frontend: sobre el plan seleccionado, el usuario carga uno o
varios `tarjetazo` para simular; cuando descarta la simulación, los limpia todos
de una.

## Decisiones tomadas (brainstorming)

- `deuda` y `tarjetazo` **se materializan idéntico**: como Préstamo pero **sin la
  entrada de capital** (solo las cuotas de salida, con tasas/IVA/corrimiento por
  finde). No se genera la entry `plan_movimiento_entrada`.
- **`principal_amount = 0`** para ambos (no entra capital). Lo fija el backend.
- **`start_date = installment_start_date`** (lo fija el backend). La columna es
  `NOT NULL` y clave de orden del listado; se mantiene poblada sin pedir una
  fecha redundante.
- `deuda` se crea por el **POST genérico** (`/plans/{plan_id}/movements`); el
  usuario manda cuotas y tasas.
- `tarjetazo` se crea **solo** por un **endpoint dedicado** a partir de una
  tarjeta; el POST genérico **rechaza** `kind=tarjetazo`. No se guarda FK a la
  tarjeta (snapshot).
- El **borrado masivo** es **solo para `tarjetazo`** (no genérico por kind).
- La razón de `tarjetazo` se documenta en este spec (Motivación) y con un
  comentario junto a `DEBT_KINDS` en el código.

## Modelo y enum

`plan_movements.kind` pasa a admitir 5 valores:
`ingreso`, `deuda_informal`, `prestamo`, `deuda`, `tarjetazo`.

- Modelo: `app/models/plan_movement.py:18` — agregar `'deuda'` y `'tarjetazo'` al
  `Enum(..., name="plan_movement_kind")`.
- No cambian columnas. `principal_amount` y `start_date` siguen `NOT NULL`.

## Constantes de kinds (servicio)

- `MOVEMENT_KINDS` = kinds creables por el **POST genérico**:
  `("ingreso", "deuda_informal", "prestamo", "deuda")`. **`tarjetazo` queda
  fuera** → crear `kind=tarjetazo` por el genérico da `kind_invalid`.
- `DEBT_KINDS = ("deuda", "tarjetazo")` = kinds con comportamiento "deuda sin
  entrada". Se **define en `app/services/cash_flow/plan_movements.py`** (módulo
  de más abajo) y se importa desde el servicio. Razón: `plan_movement_service`
  ya importa `materialize_plan_movement` desde ese módulo; definir la constante
  ahí mantiene la dirección de import y **evita el ciclo** que habría si la
  materialización importara `DEBT_KINDS` del servicio. Comentario de Motivación
  junto a la constante:
  ```python
  # deuda: deuda en cuotas, sin entrada de capital (POST genérico).
  # tarjetazo: igual que deuda, pero modela una compra de impulso desde una
  #   tarjeta; se crea por POST .../movements/tarjetazos y se puede borrar en
  #   bloque (DELETE .../movements/tarjetazos).
  DEBT_KINDS = ("deuda", "tarjetazo")
  ```

## Materialización (común a deuda y tarjetazo)

`app/services/cash_flow/plan_movements.py` — `_target_entries`:

- Rama nueva `elif kind in DEBT_KINDS:` = exactamente el bloque de **cuotas** de
  `prestamo` (salidas, `source_type="plan_movimiento"`, `is_income=False`, tasa
  efectiva con IVA, `_monthly_dates(installment_start_date, total_installments,
  horizon, shift=True)`), **sin** el target `plan_movimiento_entrada`.

## `deuda`: creación por el endpoint genérico

`POST /plans/{plan_id}/movements` con `kind="deuda"`.

**Manda el usuario:** `currency_id`, `description` (opcional), `installment_amount`,
`installment_start_date`, `total_installments`, `financing_rate` (opcional),
`overdue_rate` (opcional), `rates_add_vat` (opcional, default `True`).

**Fija el backend:** `principal_amount = Decimal(0)`,
`start_date = installment_start_date`, `income_duration_months = None`.

### Schema (Pydantic)

`app/schemas/plan_movement.py` — `PlanMovementCreate`:
- `principal_amount: Decimal | None = None` (deja de ser obligatorio en el schema).
- `start_date: date | None = None` (idem).

La obligatoriedad de ambos para `ingreso`/`deuda_informal`/`prestamo` pasa al
servicio. `PlanMovementUpdate` y `PlanMovementOut` no cambian de tipos
(`principal_amount` sale `Decimal`, `0` para estos kinds; `start_date` poblado).

### Validación (servicio) — `app/services/plan_movement_service.py`

- `_check_foreign_fields`: rama para `DEBT_KINDS` → acepta `INSTALLMENT_FIELDS` +
  `RATE_FIELDS`; rechaza `INCOME_FIELD` (`income_duration_months`) con
  `movement_fields_invalid`.
- `create_movement`:
  - `principal_amount is None or <= 0 → amount_invalid` aplica solo a kinds que
    **no** están en `DEBT_KINDS` (para `DEBT_KINDS` el backend lo fija en `0`).
  - Para kinds fuera de `DEBT_KINDS`, si `start_date is None` →
    `movement_fields_invalid` (hoy lo garantizaba Pydantic; al volverse opcional
    en el schema, el chequeo pasa al servicio).
  - Para `deuda`: exige las 3 cuotas (`_validate_installments`); arma la fila con
    `principal_amount=Decimal(0)`, `start_date=payload.installment_start_date`,
    `income_duration_months=None`, `installment_*` y `rate_*` del payload,
    `rates_add_vat` (default `True`).
- `update_movement`:
  - `_check_foreign_fields(movement.kind, present)` ya cubre `DEBT_KINDS`.
  - La validación final de cuotas pasa de `if movement.kind == "prestamo"` a
    `if movement.kind in ("prestamo",) + DEBT_KINDS`.
  - Si para un `DEBT_KINDS` se actualiza `installment_start_date`, el servicio
    re-fija `start_date = installment_start_date`.
  - `kind` no es editable (igual que hoy). Un `tarjetazo` existente puede
    editarse por el PATCH genérico como cualquier `DEBT_KINDS` (es un snapshot;
    no se re-deriva de la tarjeta).

## `tarjetazo`: creación por endpoint dedicado

`POST /plans/{plan_id}/movements/tarjetazos`.

**Manda el usuario (schema nuevo `TarjetazoCreate`):**
`installment_amount`, `total_installments`, `credit_card_id`, `currency_id`.

**Deriva el backend (snapshot de la tarjeta):**
- `description` = `Institution.name` de la tarjeta (`credit_card.institution_id`
  → `institutions.name`). Entra en `String(100)`.
- `financing_rate` / `overdue_rate` = par **local** o **usd** de la tarjeta según
  la moneda (ver Mapeo de tasas).
- `rates_add_vat` = `credit_card.rates_add_vat`.
- `installment_start_date` = primer pago calculado del cierre/vencimiento (ver
  Cálculo del primer pago); `start_date` = ese mismo valor.
- `principal_amount = Decimal(0)`, `income_duration_months = None`,
  `kind = "tarjetazo"`.

### Mapeo de tasas (la tarjeta no tiene moneda; tasas desdobladas)

La `credit_card` tiene `financing_rate_local`/`financing_rate_usd`,
`overdue_rate_local`/`overdue_rate_usd` y un único `rates_add_vat`. Según la
`Currency` que manda el usuario:

- `currency.is_legal_tender` (pesos) → `*_local`.
- en otro caso (dólar) → `*_usd`.

### Cálculo del primer pago (`installment_start_date`)

A partir de `credit_card.closing_day`, `credit_card.due_day` y `today` (fecha de
creación; inyectable en tests). La "fecha de compra" es `today`.

```
last_day(y, m)           # calendar.monthrange(y, m)[1]
closing_this = date(today.year, today.month, min(closing_day, last_day(today.year, today.month)))
if today <= closing_this:
    cy, cm = (today.year, today.month)          # entra al cierre de este mes
else:
    cy, cm = next_month(today.year, today.month)  # entra al del mes siguiente
if due_day >= closing_day:
    dy, dm = (cy, cm)                            # vence el mismo mes del cierre
else:
    dy, dm = next_month(cy, cm)                  # vence el mes siguiente
installment_start_date = date(dy, dm, min(due_day, last_day(dy, dm)))
```

Ejemplo (cierre 20, vencimiento 30): compra ≤ 20-jun → `30-jun`; compra ≥ 21-jun
→ `30-jul`. La fecha se guarda **nominal** (sin correr por finde); las cuotas las
corre la materialización `DEBT_KINDS` (`shift=True`), igual que deuda/préstamo.

### Validación (servicio) — `create_tarjetazo(db, user, plan_id, payload, today=None)`

- `_get_owned_plan` (+ rechazo si `plan.is_default` → `default_plan_no_movements`).
- `require_user_currency(db, user, currency_id)` y además
  `currency.allowed_in_credit_card` (Peso o Dólar). Si no es de tarjeta →
  `currency_not_available`.
- `_require_card(db, user, credit_card_id)` (de `credit_card_service`) →
  `not_found` si no es del usuario.
- `_validate_installments(installment_amount, installment_start_date_calculado,
  total_installments)` (monto > 0, total ≥ 1).
- Arma la fila con los campos derivados, `db.flush()`,
  `materialize_plan_movement(db, movement.id, today=today)`, `commit`, devuelve.

### Endpoint

- `POST /plans/{plan_id}/movements/tarjetazos`, body `TarjetazoCreate`,
  `response_model=PlanMovementOut`, `status_code=201`.
- Se declara **antes** de las rutas paramétricas `/movements/{movement_id}` para
  evitar ambigüedad (ver Orden de rutas).

## Endpoint: borrar todos los `tarjetazo` de un plan

- **Ruta:** `DELETE /plans/{plan_id}/movements/tarjetazos`.
- **Servicio:** `delete_tarjetazos(db, user, plan_id) -> int`:
  - `_get_owned_plan` (del usuario; si no, `not_found`).
  - Borra las `cash_flow_entries` con
    `source_type in ("plan_movimiento", "plan_movimiento_entrada")` y
    `source_id in (<ids de los tarjetazo del plan>)`.
  - Borra los `plan_movements` con `kind="tarjetazo"` del plan.
  - Devuelve la cantidad borrada. No corre el motor.
- **Respuesta:** `200` con `{"deleted": <n>}` (0 si no había).

## Orden de rutas (`app/routers/plan_movements.py`)

`movement_id` es `uuid.UUID`. Las rutas literales `/movements/tarjetazos` (POST y
DELETE) se declaran **antes** de `/movements/{movement_id}` (PATCH/DELETE), porque
ante un path no-UUID FastAPI devuelve 422 en la ruta paramétrica en vez de caer a
la siguiente. (El POST genérico es sobre `/movements`, sin colisión.)

## Errores

Se reutilizan códigos existentes (`app/core/errors.py`): `kind_invalid`,
`movement_fields_invalid`, `installments_invalid`, `amount_invalid`, `not_found`,
`empty_patch`, `default_plan_no_movements`, `currency_not_available`. No se
agregan códigos nuevos.

## Migración

- `op.execute("ALTER TYPE plan_movement_kind ADD VALUE IF NOT EXISTS 'deuda'")`
- `op.execute("ALTER TYPE plan_movement_kind ADD VALUE IF NOT EXISTS 'tarjetazo'")`
- (Postgres 16 admite `ADD VALUE` dentro de la transacción de la migración porque
  el valor no se usa en la misma transacción.)
- **`downgrade`:** Postgres no permite `DROP VALUE`. El downgrade recrea el tipo
  sin `deuda`/`tarjetazo` (rename del viejo → crear el nuevo → `ALTER COLUMN ...
  TYPE` con cast → drop del viejo). **Falla si existen filas con esos kinds**; hay
  que borrarlas antes de revertir. Se documenta en la migración.

## Tests

`tests/test_plan_movements.py` y `tests/test_cashflow_engine_plan_movements.py`.

**Materialización (deuda y tarjetazo):**
1. Crea y materializa **solo cuotas**: N entries `plan_movimiento`
   (`is_income=False`), **ninguna** `plan_movimiento_entrada`.
2. `principal_amount == 0`, `start_date == installment_start_date`,
   `income_duration_months is None`.
3. Cuotas con `financing_rate`/`overdue_rate` efectivos (IVA) igual que Préstamo.

**`deuda` (POST genérico):**
4. Rechaza `income_duration_months` → 422 `movement_fields_invalid`.
5. Exige cuotas (crear sin `installment_*`) → 422 `installments_invalid`.
6. Update: cambiar `installment_amount` rematerializa; cambiar
   `installment_start_date` re-fija `start_date`.

**`tarjetazo` (POST dedicado):**
7. POST genérico con `kind=tarjetazo` → 422 `kind_invalid`.
8. Mapeo de tasas: moneda legal → `*_local`; dólar → `*_usd`; copia
   `rates_add_vat` de la tarjeta.
9. Cálculo de fecha (inyectando `today`): las **dos** ramas del ejemplo
   (`today <= closing_day` → vencimiento de este mes; `today > closing_day` →
   mes siguiente), y el caso `due_day < closing_day`.
10. `description == Institution.name` de la tarjeta.
11. Moneda no `allowed_in_credit_card` (UI/UR) → `currency_not_available`.
12. Tarjeta de otro usuario → `404 not_found`.

**Delete:**
13. Individual: borra el movimiento y sus entries.
14. Masivo (solo tarjetazo): con M `tarjetazo` (+ otros kinds) →
    `200 {"deleted": M}`; borra esos y sus entries, **no** toca otros kinds. Sin
    tarjetazo → `{"deleted": 0}`. Plan de otro usuario → `404`.

## Touchpoints (resumen)

| Archivo | Cambio |
|---|---|
| `app/models/plan_movement.py:18` | enum +`deuda` +`tarjetazo` |
| `app/schemas/plan_movement.py` | `principal_amount`, `start_date` opcionales en Create; **nuevo** `TarjetazoCreate` |
| `app/services/cash_flow/plan_movements.py` | **definir** `DEBT_KINDS` + comentario; materialización rama `DEBT_KINDS` (sin entrada) |
| `app/services/plan_movement_service.py:16` | `MOVEMENT_KINDS` += `deuda` (no tarjetazo); importar `DEBT_KINDS` |
| `app/services/plan_movement_service.py:41` | `_check_foreign_fields` rama `DEBT_KINDS` |
| `app/services/plan_movement_service.py:~60` | `create_movement` (deuda: principal=0, start_date) |
| `app/services/plan_movement_service.py:147` | `update_movement` (cuotas + re-fijar start_date) |
| `app/services/plan_movement_service.py` | **nuevo** `create_tarjetazo()` y `delete_tarjetazos()` |
| `app/routers/plan_movements.py` | `POST` y `DELETE` `.../movements/tarjetazos` (antes de `{movement_id}`) |
| `alembic/versions/<rev>_*.py` | `ADD VALUE 'deuda'`, `'tarjetazo'` |

(Lecturas/imports que usa `create_tarjetazo`: `CreditCard` y `_require_card` de
`credit_card_service`, `Institution`, `Currency` con `is_legal_tender` /
`allowed_in_credit_card`, `compute_event_date` no se usa para la fecha del primer
pago — se calcula nominal; sí lo usa la materialización.)

## Fuera de alcance (YAGNI)

- Simulación separada que no afecte el cash flow real (tarjetazo impacta igual
  que deuda).
- Vincular el `plan_movement` a la tarjeta (FK) o re-derivar tasas/fecha al
  editar (es snapshot).
- Endpoint genérico de borrado por kind (solo `tarjetazo`).
- Tarjetazo en monedas fuera de las de tarjeta (solo `allowed_in_credit_card`).
- UI/frontend; `principal_amount` nullable; nuevos códigos de error.

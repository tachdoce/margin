# user_financial_settings — monto necesario del mes — Diseño

> El usuario carga "cuánto supone que necesita para lo que resta del mes" (un monto por usuario, en moneda
> legal). Se guarda en una tabla nueva 1:1 con users, se actualiza **junto con** las `cash_balances` en una
> sola llamada atómica, y **reemplaza** el `remaining_spending` del mes actual en el timeline (el prorrateo
> del dial era provisional; este valor lo sustituye cuando está cargado).

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice: tabla nueva + modificar el endpoint `cash_balances` + integrar al timeline.
- **Cierre:** rama `feat/user-financial-settings`, **squash-merge** a `main`.
- **Dependencias (ya en `main`):** `cash_balances` (tabla + endpoints) ✓; `feat/timeline-monthly-totals`
  (lógica de `remaining_spending` en `get_timeline`) ✓.
- **Fuera de alcance:** otros ajustes financieros per-usuario (la tabla queda lista pero hoy 1 columna);
  conversión de moneda (el monto ya es legal); impacto en meses 2+ del timeline.

---

## 1. Tabla `user_financial_settings`

1:1 con users (PK = `user_id`), pensada como "ajustes financieros del usuario" (extensible).

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `user_id` | uuid PK FK→users | No | dueño |
| `monthly_need_amount` | numeric(12,2) | **Sí** | monto que el usuario supone necesitar para el resto del mes, en moneda legal. Null = sin cargar |
| `created_at` | timestamptz | No | server_default now() |
| `updated_at` | timestamptz | No | server_default now() + onupdate now() |

`monthly_need_amount` nullable: una fila puede existir con el valor sin cargar (y deja lugar a columnas
futuras). **Borrado:** hard-delete. Registrar el modelo en `app/models/__init__.py`. Migración aditiva
(`alembic upgrade head`), sin recrear la DB.

---

## 2. Endpoint `cash_balances` (modificado)

Se **elimina** la idea de endpoints `/financial-settings` separados: `cash_balances` es el único lugar para
la "foto financiera" (efectivo por moneda + monto necesario).

**Respuesta (objeto, antes era array):**
```
{ "balances": [ {"currency_id": 1, "amount": "15000.00"}, ... ], "monthly_need_amount": "50000.00" | null }
```

- `GET /cash-balances` → ese objeto. `monthly_need_amount` = el valor guardado, o `null` si no hay fila / está null.
- `PUT /cash-balances`, body `{ "balances": [...], "monthly_need_amount"?: ... }`:
  - Valida `balances` como hoy: holdable (`require_holdable_currency` → `currency_not_available`), sin
    duplicados (`duplicate_currency`), `amount >= 0` (`amount_negative`).
  - `monthly_need_amount` es **opcional** (se detecta con `model_fields_set`, patrón del PATCH de financings):
    - **ausente** → no toca el valor guardado.
    - **presente con valor** → valida `>= 0` (`amount_negative`) y upsertea la fila de `user_financial_settings`.
    - **presente en `null`** → setea la columna en null (lo limpia).
  - **Atómico:** valida TODO el body (balances + monto) antes de cualquier escritura; recién después upsertea.
  - Devuelve el objeto `{ balances, monthly_need_amount }`.

---

## 3. Schemas (`app/schemas/cash_balance.py`)

- `CashBalancesSet` (body del PUT): + `monthly_need_amount: Decimal | None = None`. Se usa
  `model_fields_set` en el service para distinguir "ausente" de "null explícito".
- Respuesta nueva (objeto): `CashBalancesView` = `{ balances: list[CashBalanceOut], monthly_need_amount:
  Decimal | None }`. `GET` y `PUT` la devuelven (`response_model=CashBalancesView` en el router).
- `CashBalanceOut` / `CashBalanceSetItem` quedan igual.

---

## 4. Service (`app/services/cash_balance_service.py`)

- `get_balances` → devuelve `CashBalancesView` (los balances de hoy + `monthly_need_amount` leído de
  `user_financial_settings`, o null si no hay fila).
- `set_balances` → además de los balances, si `monthly_need_amount` ∈ `model_fields_set`: valida (`>= 0` si no
  null) y upsertea la fila de `user_financial_settings` (`db.get(UserFinancialSettings, user.id)`; crear o
  setear). Mantiene la validación-todo-antes-de-escribir y el commit único.

---

## 5. Integración con el timeline (`app/services/cash_flow_entry_service.py`)

`get_timeline` ya calcula `remaining_spending` del mes actual como `dial_prorated` (línea del ancla:
`remaining_spending = dial_prorated if key == current_key else dial`). El cambio:

- Antes del loop, leer una vez `monthly_need = user_financial_settings.monthly_need_amount` del usuario
  (None si no hay fila o está null).
- En el branch del **ancla** (`prev_balance is None`), para el **mes actual** (`key == current_key`):
  `remaining_spending = monthly_need if monthly_need is not None else dial_prorated`.
- Resto sin cambios (meses futuros y arrastre usan `dial`; meses pasados quedan en 0).
- El monto ya está en moneda legal → **sin conversión**.

`MonthOut` **no cambia de forma**: solo cambia el origen del `remaining_spending` del mes actual.

---

## 6. Cambios de contrato

- `GET`/`PUT /cash-balances`: respuesta de **array → objeto** `{ balances, monthly_need_amount }`. La web que
  consume `cash_balances` lee `resp.balances` en vez del array directo.
- `PUT /cash-balances`: el body acepta el campo opcional `monthly_need_amount`.
- Timeline: el `remaining_spending` del mes actual puede venir del monto del usuario (mismo campo y forma).

---

## 7. Archivos

| Archivo | Cambio |
|---|---|
| `app/models/user_financial_settings.py` | modelo `UserFinancialSettings` + registrar en `app/models/__init__.py` |
| `alembic/versions/<rev>_create_user_financial_settings.py` | crea la tabla |
| `app/schemas/cash_balance.py` | `CashBalancesSet` + `monthly_need_amount`; nueva `CashBalancesView` |
| `app/services/cash_balance_service.py` | `get_balances`/`set_balances` con el monto + view |
| `app/routers/cash_balances.py` | `response_model=CashBalancesView` en GET y PUT |
| `app/services/cash_flow_entry_service.py` | `get_timeline`: mes actual lee `monthly_need` |

---

## 8. Tests

Postgres `margin_test` (`create_all` + savepoint). Fixtures de `cash_balances` ya existen.

- **Modelo** (`tests/test_user_financial_settings.py` o dentro de `test_cash_balances.py`): round-trip de la
  tabla (insertar + leer; null permitido).
- **GET**: sin fila → `{"balances": [...], "monthly_need_amount": null}`; con fila → trae el monto.
- **PUT**: actualiza solo balances (monto ausente → no toca); solo el monto (balances vacíos); ambos a la vez;
  `null` explícito limpia el monto; `amount_negative` con monto < 0; atomicidad (monto inválido → no se aplica
  ni el monto ni los balances).
- **Timeline** (`tests/test_get_cash_flow_entries.py`): mes actual con `monthly_need_amount` cargado →
  `remaining_spending` = ese valor (no el prorrateo); sin fila/null → cae al `dial_prorated`. `today` inyectado.

---

## 9. Plan de implementación (orientativo)

Un slice (`feat/user-financial-settings`), TDD: modelo + migración → schemas (body opcional + view) → service
(get/set con el monto, atómico) → router (response_model) → integración timeline (mes actual lee el monto) →
suite verde → cierre (squash-merge). Sin tocar Notion.

# cash_balances — efectivo actual del usuario — Diseño

> Saber **cuánto efectivo tiene el usuario en este momento**, por moneda. Snapshot (un monto por moneda, se
> sobreescribe), pensado genérico para multi-país: las monedas que un usuario puede tener son las del catálogo
> `currencies` con `allowed_in_credit_card = true` de su país. Más adelante el PlanEngine/timeline lo usará como
> punto de partida del flujo; por ahora es solo la tabla + endpoints para leer y setear.

- **Fecha:** 2026-06-10
- **Estado:** aprobado para implementar
- **Alcance:** **backend only**, un slice: tabla + migración + GET + PUT masivo.
- **Cierre:** rama `feat/cash-balances`, **squash-merge** a `main`.
- **Fuera de alcance:** la web; la integración con engines (PlanEngine/timeline).

---

## 1. Concepto: monedas "holdable"

Las monedas que un usuario puede tener como efectivo = `currencies` con
`country_code = user.country_code AND allowed_in_credit_card = true`. Para UY: **Peso (1)** y **Dólar (3)**.

> El flag `allowed_in_credit_card` se reusa como "moneda de verdad que el usuario puede tener" (marca justo
> esas). Se deja anotado que el nombre del flag viene de tarjetas; la regla es deliberada y genérica a futuros
> países.

Helper nuevo en `app/services/scoping.py`:
- `holdable_currencies(db, user) -> list[Currency]`: las del país del usuario con `allowed_in_credit_card`,
  ordenadas por `id`.
- `is_holdable_currency(db, user, currency_id) -> bool` (o `require_holdable_currency` que levanta
  `currency_not_available` si no lo es). Para la validación del PUT.

---

## 2. Tabla `cash_balances`

| Columna | Tipo | NULL | Notas |
|---|---|---|---|
| `user_id` | uuid FK → users | No | **PK compuesta** con `currency_id` |
| `currency_id` | smallint FK → currencies | No | **PK compuesta** con `user_id` |
| `amount` | numeric(12,2) | No | efectivo actual en esa moneda. `>= 0` |
| `created_at` | timestamp | No | server_default now() |
| `updated_at` | timestamp | No | server_default now(), onupdate now() |

- **PK compuesta `(user_id, currency_id)`** — una fila por usuario+moneda; garantiza unicidad sin columna `id`
  aparte (mismo patrón que `currency_rates`). Registrar el modelo en `app/models/__init__.py`.
- Migración **aditiva** (tabla nueva, `alembic upgrade head`, sin recrear la DB).
- **Sin pre-seed** al registrarse: las filas se crean recién cuando el usuario carga un monto. El GET completa
  con `0.00` las monedas holdable sin fila (robusto a monedas/países nuevos, sin backfill).

---

## 3. GET /cash-balances → 200 `[CashBalanceOut]`

Solo lectura. Devuelve **una entrada por cada moneda holdable** del usuario, con su efectivo actual.

- Tomar las `holdable_currencies(db, user)` (orden por `currency_id`).
- LEFT JOIN con las `cash_balances` del usuario; `amount` = el guardado o `0.00` si no hay fila.
- Forma de cada entrada: `{ "currency_id": int, "amount": Decimal }`. (El nombre/símbolo los resuelve el
  cliente con el catálogo del bootstrap; no se repiten acá.)

Ejemplo (UY, el usuario cargó 200 en dólares y nada en pesos):
```json
[
  { "currency_id": 1, "amount": "0.00" },
  { "currency_id": 3, "amount": "200.00" }
]
```

Errores: `401 unauthenticated`.

---

## 4. PUT /cash-balances → 200 `[CashBalanceOut]`

Setea el efectivo de **una o varias** monedas en una sola request, **atómico** (todo-o-nada).

**Body:**
```json
{
  "balances": [
    { "currency_id": 1, "amount": "15000.00" },
    { "currency_id": 3, "amount": "200.00" }
  ]
}
```

**Validaciones (sobre todo el body antes de escribir nada):**
1. Sin `currency_id` repetido en `balances` → si hay, 422 `duplicate_currency`.
2. Cada `currency_id` es una moneda **holdable** del usuario → si no, 422 `currency_not_available`.
3. Cada `amount >= 0` → si no, 422 `amount_negative`. (0 es válido: "no tengo nada en esa moneda".)

Si alguna falla, **no se aplica ninguna** (una transacción).

**Upsert:** por cada item, INSERT si no existe la fila `(user_id, currency_id)` o UPDATE del `amount` si existe.
`updated_at = now()`. Las monedas holdable que **no** vengan en el body quedan como estaban.

**Response:** la **lista completa** (misma forma que el GET: una entrada por moneda holdable, con los montos ya
actualizados). Así el cliente recibe el estado entero tras el guardado.

Errores: `401`, `422 duplicate_currency`, `422 currency_not_available`, `422 amount_negative`.

> Body con `balances` vacío: no-op válido (no escribe nada), devuelve la lista actual. Sin `DELETE`: poner
> `amount = 0` representa "no tengo efectivo en esa moneda".

---

## 5. Schemas (`app/schemas/cash_balance.py`)

```text
CashBalanceOut(BaseModel):     # GET y PUT response, por entrada
    currency_id: int
    amount: Decimal

CashBalanceSetItem(BaseModel): # cada item del body del PUT
    currency_id: int
    amount: Decimal

CashBalancesSet(BaseModel):    # body del PUT
    balances: list[CashBalanceSetItem]
```

`Decimal` se serializa como string (convención de plata).

---

## 6. Códigos de error nuevos (`errors.py`)

| code | HTTP | mensaje |
|---|---|---|
| `amount_negative` | 422 | El monto no puede ser negativo. |
| `duplicate_currency` | 422 | No repitas la misma moneda. |

Reuso: `currency_not_available` (422), `unauthenticated` (401).

---

## 7. Archivos

| Archivo | Cambio |
|---|---|
| `app/models/cash_balance.py` | modelo `CashBalance` (PK compuesta) + registrar en `app/models/__init__.py` |
| `alembic/versions/<rev>_create_cash_balances.py` | crea la tabla |
| `app/services/scoping.py` | + `holdable_currencies` / `require_holdable_currency` |
| `app/schemas/cash_balance.py` | Out / SetItem / Set |
| `app/services/cash_balance_service.py` | `get_balances` (derivado) + `set_balances` (validar todo → upsert) |
| `app/routers/cash_balances.py` | GET + PUT; registrar en `main.py` |
| `app/core/errors.py` | + 2 codes |

No va al bootstrap (dato dinámico del usuario, con su propio GET — coherente con GLOBAL).

---

## 8. Tests (`tests/test_cash_balances.py`)

Postgres `margin_test` (`create_all` + savepoint). Base: `seed_uy_currency` (Peso id 1) + sembrar Dólar (id 3,
`allowed_in_credit_card=true`) y una no-holdable (p.ej. UI id 4, `allowed_in_credit_card=false`). Usuario vía
`/auth/register`.

- **GET**: usuario sin nada → lista con las holdable en `0.00` (Peso + Dólar), **sin** la UI; refleja montos
  guardados; orden por `currency_id`; 401 sin token.
- **PUT**: setea 2 monedas atómico → response trae la lista completa con los nuevos montos; vuelve a setear una
  → la actualiza (upsert, no duplica); moneda no holdable (UI) → 422 `currency_not_available` y **no** escribe
  nada; `amount` negativo → 422 `amount_negative`; `amount = 0` válido; `currency_id` repetido en el body → 422
  `duplicate_currency`; atomicidad: si una entrada falla, ninguna se aplica (verificar con un GET posterior).

---

## 9. Plan (orientativo)

Un slice (`feat/cash-balances`), TDD: modelo + migración → scoping helper → schemas + 2 codes → `get_balances` +
GET → `set_balances` + PUT → suite verde → cierre. Sin Notion.

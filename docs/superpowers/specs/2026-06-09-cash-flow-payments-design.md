# cash_flow_payments — CRUD de pagos/cobros — Diseño

> Primer sub-proyecto del grupo **cash-flow-entries** (de 2): los 4 endpoints de `cash_flow_payments`, anidados
> bajo `/cash-flow-entries/{entry_id}/payments`. El usuario registra movimientos reales (pago/cobro) o
> planificados (intención dentro de un plan) contra una entry del flujo. El segundo sub-proyecto (la línea de
> tiempo: `GET /cash-flow-entries`, `by-source`, `PATCH`) va después.

- **Fecha:** 2026-06-09
- **Estado:** aprobado para implementar
- **Alcance:** **backend only** (la web del flujo de dinero va después, sección propia).
- **Cierre:** rama `feat/cash-flow-payments`, **squash-merge** a `main`.
- **Fuente de verdad (Notion):** `Endpoints → Flujo de dinero →` {POST, GET, PATCH, DELETE} `cash-flow-payments`
  y `BD → Flujo de dinero → cash_flow_payments`.

---

## 1. Contexto del terreno (ya existe)

- Tablas/modelos `cash_flow_entries`, `cash_flow_payments`, `plans`, `plan_movements` y `currency_rates` ya
  están. Los motores ya materializan `cash_flow_entries`.
- `cash_flow_entries` tiene **`user_id` directo** → la pertenencia se chequea con `cfe.user_id == user.id`
  (no hay que subir por la fuente).
- `cash_flow_payments`: `id`, `cash_flow_entry_id` (FK CASCADE), `amount` numeric(12,2), `note` varchar(100)
  nullable, `plan_id` FK nullable, `planned_date` nullable, `created_at`, `updated_at`.
- `source_type` de la entry es un enum con 7 valores:
  `gasto, deuda, deuda_abierta, ingreso, plan_movimiento, plan_movimiento_entrada, tarjeta_credito`.

**Greenfield en este sub-proyecto:** router, service y schemas de pagos + códigos de error nuevos.

---

## 2. Decisión: `tarjeta_credito` cuenta como entry "real"

El spec de pagos en Notion se escribió **antes** del subdominio de tarjetas y enumera los tipos "reales" como
`gasto/deuda/deuda_abierta/ingreso`, sin `tarjeta_credito`. Un resumen de tarjeta es un egreso real que el
usuario paga, así que **`tarjeta_credito` se trata como entry real** (acepta pago real + planificado).

Para que esto sea robusto a futuros `source_type`, la regla se codifica **al revés**: la única excepción son
las **entries de plan** (`plan_movimiento`, `plan_movimiento_entrada`); **cualquier otro** tipo es "real".

```python
PLAN_ENTRY_TYPES = {"plan_movimiento", "plan_movimiento_entrada"}
def _is_plan_entry(entry) -> bool:
    return entry.source_type in PLAN_ENTRY_TYPES
```

**Acción asociada:** actualizar las páginas Notion `POST cash-flow-payments` y `GET cash-flow-payments` para
incluir `tarjeta_credito` entre los tipos reales (framing "la excepción es la entry de plan").

---

## 3. Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `app/routers/cash_flow_payments.py` | Router thin, `Depends(get_current_user)`, prefijo `/cash-flow-entries/{entry_id}/payments`. Registrar en `main.py`. |
| `app/services/cash_flow_payment_service.py` | `create/list/update/delete` + helpers `_load_owned_entry`, `_entry_plan_id`. Controla commit, levanta `AppError`. |
| `app/schemas/cash_flow_payment.py` | `PaymentCreate`, `PaymentUpdate`, `PaymentOut`, `PaymentListItem`. |
| `app/core/errors.py` | Códigos nuevos (ver §6). |

El router es delgado: traduce path/query/body a llamadas del service y serializa. Toda la lógica y validación
vive en el service.

---

## 4. Schemas

- **`PaymentCreate`** (body POST): `amount: Decimal`, `note: str | None = None`, `plan_id: UUID | None = None`,
  `planned_date: date | None = None`.
- **`PaymentUpdate`** (body PATCH): `amount: Decimal | None = None`, `note: str | None = None`,
  `planned_date: date | None = None`. La distinción "vino o no" para `note`/`planned_date` se hace con
  `model_fields_set` (porque `null` es un valor válido para `note`).
- **`PaymentOut`** (response POST/PATCH): `id, cash_flow_entry_id, amount, note, plan_id, planned_date,
  created_at`.
- **`PaymentListItem`** (response GET): `id, cash_flow_entry_id, amount, note, is_planned, planned_date,
  created_at`. **Sin `plan_id`**; en su lugar `is_planned: bool` (derivado `plan_id is not None`).

> Pydantic v2 serializa `Decimal` como string (igual que el resto del proyecto). `created_at` ISO-8601.

---

## 5. Endpoints

### 5.1 POST /cash-flow-entries/{entry_id}/payments → 201 `PaymentOut`
Validaciones (en orden):
1. Entry `{entry_id}` existe y `user_id == user` → si no, 404 `not_found`.
2. Coherencia: `plan_id` y `planned_date` o ambos presentes o ambos ausentes → si solo uno, 422
   `planned_payment_incomplete`.
3. Si vino `plan_id`: el plan existe y es del user → si no, 404 `not_found`.
4. Pagabilidad (§2):
   - **real** (sin `plan_id`): si `_is_plan_entry(entry)` → 409 `entry_not_payable`; si no, acepta.
   - **planificado** (con `plan_id`): si la entry **no** es de plan → acepta; si es de plan → su plan
     (`_entry_plan_id`) debe ser `== plan_id`, si no → 409 `entry_not_payable`.
5. `amount > 0` → si no, 422 `amount_invalid`.

Insert una fila (`cash_flow_entry_id` del path; `amount`, `note`, `plan_id`, `planned_date` del body), commit,
201 con `PaymentOut`.

### 5.2 GET /cash-flow-entries/{entry_id}/payments?plan_id=&month= → 200 `[PaymentListItem]`
1. `plan_id` en query → si falta, 422 `plan_id_required`.
2. Si vino `month`: parsear `YYYY-MM` → si no, 422 `month_invalid`.
3. Entry existe y es del user → 404 `not_found`.
4. Plan existe y es del user → 404 `not_found`.
5. Query: `cash_flow_payments` con `cash_flow_entry_id = entry_id` y (`plan_id IS NULL` OR `plan_id = :plan_id`).
   Si vino `month`: además `date_trunc('month', COALESCE(planned_date, created_at::date)) = mes`. Orden
   `created_at DESC`.
6. Serializar con `is_planned = (plan_id is not None)`. 200 con el array (puede ser `[]`).

### 5.3 PATCH /cash-flow-entries/{entry_id}/payments/{payment_id} → 200 `PaymentOut`
1. Entry existe y es del user → 404 `not_found`.
2. Pago `{payment_id}` existe y `cash_flow_entry_id == entry_id` → si no, 404 `not_found`.
3. El body trae al menos uno de `amount`/`note`/`planned_date` (vía `model_fields_set`) → si no, 422
   `empty_patch`.
4. Si vino `amount`: `> 0` → si no, 422 `amount_invalid`.
5. Si vino `planned_date` (la **fila guardada** decide):
   - fila real (`plan_id IS NULL`) → 422 `planned_date_on_real_payment`.
   - fila planificada (`plan_id` con valor) → `planned_date` debe ser fecha válida y **no null** → si null,
     422 `planned_date_invalid`. (Formato inválido lo ataja Pydantic con 422.)
6. Update solo las columnas presentes; `plan_id`, `cash_flow_entry_id`, `created_at` no se tocan;
   `updated_at = now()`. 200 con `PaymentOut`.

### 5.4 DELETE /cash-flow-entries/{entry_id}/payments/{payment_id} → 204
1. Entry existe y es del user → 404 `not_found`.
2. Pago existe y es de esa entry → 404 `not_found`.
3. `DELETE` físico. 204 sin cuerpo. (Sin 409: siempre se puede anular.)

---

## 6. Códigos de error nuevos (`errors.py`)

| code | HTTP | mensaje |
|---|---|---|
| `entry_not_payable` | 409 | Esta entrada no acepta este pago. |
| `amount_invalid` | 422 | El monto debe ser mayor a 0. |
| `planned_payment_incomplete` | 422 | Un pago planificado necesita plan y fecha. |
| `plan_id_required` | 422 | Falta indicar el plan. |
| `month_invalid` | 422 | El mes indicado no es válido. |
| `planned_date_on_real_payment` | 422 | No se puede agendar fecha en un pago real. |
| `planned_date_invalid` | 422 | La fecha agendada no es válida. |

Reuso: `not_found` (404), `empty_patch` (422), `unauthenticated` (401). Verificar cuáles ya existen y no
duplicar (p.ej. `plan_id_required`/`month_invalid` pueden reutilizarse luego en el GET timeline del
sub-proyecto 2).

---

## 7. Tests

Postgres `margin_test` (`create_all` + savepoint). Helpers en `conftest`/módulo de test: insertar una
`CashFlowEntry` directo (con `user_id`, `source_type`, `source_id`, `amount`, `currency_id`, `is_income`), y
para entries de plan crear un `plan` + `plan_movement` y una entry con `source_type='plan_movimiento'`,
`source_id = plan_movement.id`.

- **POST** (`tests/test_cash_flow_payments_create.py`): real OK (201, shape); planificado OK (plan_id +
  planned_date); 404 entry inexistente/ajena; 404 plan inexistente/ajeno; 422 `planned_payment_incomplete`
  (solo uno); 409 `entry_not_payable` (real contra entry de plan); 409 (planificado de plan A contra entry de
  plan B); planificado contra entry real de cualquier plan OK; **`tarjeta_credito` acepta pago real**; 422
  `amount_invalid` (0 y negativo).
- **GET** (`tests/test_cash_flow_payments_list.py`): 422 `plan_id_required`; 422 `month_invalid`; 404
  entry/plan; lista reales + planificados del plan, **excluye** planificados de otro plan; `is_planned`
  correcto; filtro `month` (planificado por `planned_date`, real por `created_at`); orden `created_at DESC`;
  `[]` cuando no hay.
- **PATCH** (`tests/test_cash_flow_payments_update.py`): editar `amount`; editar `note` (incluido a `null`);
  422 `empty_patch`; 422 `amount_invalid`; 422 `planned_date_on_real_payment`; 422 `planned_date_invalid`
  (null en planificado); reagendar planificado OK; 404 entry/pago.
- **DELETE** (`tests/test_cash_flow_payments_delete.py`): 204 real; 204 planificado; 404 entry/pago;
  pago de otra entry → 404.

---

## 8. Plan de implementación (orientativo)

Un slice (`feat/cash-flow-payments`), TDD, los 4 endpoints + helpers compartidos. Orden sugerido: schemas +
errores → helpers (`_load_owned_entry`, `_entry_plan_id`) → POST → GET → PATCH → DELETE → registrar router →
suite verde → actualizar Notion (tarjeta_credito) → cierre.

# Endpoints de debts (6b) — Diseño

> Sub-slice **6b** del sub-proyecto #6 (endpoints) de **Obligaciones**. Los 3 endpoints de deudas:
> `POST /debts`, `PATCH /debts/{id}`, `GET /debts`. Un solo endpoint cubre **dos kinds** (`deuda` y
> `deuda_abierta`), inferidos del `obligation_type_id`. Cablean validación por kind →
> `ReviewEngine.review_obligation` → `CashFlowEngine.materialize_debt`/`materialize_open_debt`, en una
> transacción. El *qué* está en Notion → Endpoints → Obligaciones → POST/PATCH/GET debts.

- **Fecha:** 2026-06-08
- **Estado:** aprobado para implementar
- **Depende de:** tabla `obligations`, `review_obligation` (#5, ya con short-circuit `is_closed`),
  `materialize_debt` (#3), `materialize_open_debt` (#4), `scoping.require_user_currency`, maestras
  `obligation_types`/`priority_levels`/`institutions`/`currencies` (todo en `main`).
- **Cierre:** rama `feat/endpoints-debts`, **squash-merge** a `main`.

---

## 1. Alcance

- **Router** `app/routers/debts.py` (finito), registrado en `app/main.py`.
- **Servicio** `app/services/debt_service.py`: `create_debt`, `list_debts`, `update_debt` + helpers.
- **Schemas** `app/schemas/debt.py`: `DebtCreate`, `DebtUpdate`, `DebtOut`.
- **Error codes nuevos** en `app/core/errors.py`.

**Fuera de alcance:** DELETE + acknowledge (6c). No se toca el reviewer (el short-circuit `is_closed` ya
quedó en 6a). La extracción de validadores comunes (`_validate_priority`/`_description`/`_amount`/`_due_day`,
hoy duplicados con `expense_service`) queda **diferida** a un refactor post-6c (se replican por ahora).

---

## 2. Schemas

- **`DebtCreate`** (POST): `obligation_type_id: int`, `priority_level: int`, `institution_id: int | None =
  None`, `description: str`, `due_day: int | None = None`, `currency_id: int`, `amount: Decimal`,
  `total_installments: int | None = None`, `first_due_date: date | None = None`, `financing_rate: Decimal |
  None = None`, `overdue_rate: Decimal | None = None`, `rates_add_vat: bool | None = None`, `shift_weekends:
  bool | None = None`. (**`is_monthly_recurring` no está** — el backend lo fija en `false`.)
- **`DebtUpdate`** (PATCH): todos opcionales (`model_fields_set`): `obligation_type_id`, `priority_level`,
  `institution_id` (nullable), `description`, `due_day` (nullable), `currency_id`, `amount`,
  `total_installments` (nullable), `first_due_date` (nullable), `financing_rate` (nullable), `overdue_rate`
  (nullable), `rates_add_vat`, `shift_weekends`, `is_closed`.
- **`DebtOut`** (con `from_model`): `id, obligation_type_id, priority_level, institution_id, description,
  is_monthly_recurring, due_day, currency_id, amount, total_installments, first_due_date, financing_rate,
  overdue_rate, rates_add_vat, origin_obligation_id, shift_weekends, is_closed, review_findings, is_ready`.
  `review_findings` como `list[str]` (parseado). No expone `reviewed_at`/`user_acknowledged_at`. Plata/tasas
  como string.

---

## 3. Error codes nuevos (`app/core/errors.py`)

- `debt_type_invalid` (422, "Tipo de deuda no válido.")
- `institution_invalid` (422, "Institución no válida.")
- `rates_negative` (422, "Las tasas no pueden ser negativas.")
- `one_time_debt_inconsistent` (422, "Una deuda de un pago no admite día de vencimiento ni cuotas.")
- `debt_requires_schedule_or_date` (422, "Una deuda necesita un cronograma o una fecha de pago.")
- `open_debt_inconsistent` (422, "Una deuda abierta no admite fechas, cuotas ni tasas.")
- `debt_schedule_requires_due_day` (422, "Una deuda en cuotas necesita un día de vencimiento.")
- `debt_schedule_locked` (409, "No se puede cambiar el cronograma de una deuda con pagos registrados.")

(`installments_invalid`, `priority_level_invalid`, `description_invalid`, `amount_invalid`, `due_day_invalid`,
`currency_not_available`, `not_found`, `field_not_nullable` ya existen.)

`KIND_DEBT = ("deuda", "deuda_abierta")`. `MIN_DESCRIPTION_LENGTH = 8`. `SYSTEM_PRIORITY_LEVEL = 1`.

---

## 4. Orquestación común (POST y PATCH, 1 transacción)

```
validar → insert/update en obligations → flush
        → ReviewEngine.review_obligation(db, id)        (uniforme; el reviewer maneja is_closed internamente)
        → materialize_debt(db, id)  si kind == 'deuda'
          materialize_open_debt(db, id)  si kind == 'deuda_abierta'
        → commit → refresh → DebtOut
```
El endpoint **siempre** llama al reviewer y al motor del kind, sin branchear en `is_closed` ni evaluar
`is_ready`. Excepción o reviewer/motor → rollback total. `user_id` siempre del token. El kind no cambia entre
estado inicial y final (el cambio de tipo se restringe al mismo kind), así que el motor a invocar es estable.

---

## 5. `POST /debts` → 201

**Validaciones comunes (en orden):**
1. `obligation_type_id` existe y su `obligation_kind ∈ {'deuda','deuda_abierta'}` → si no, `debt_type_invalid`.
   Guardar el `kind`.
2. Si `kind == 'deuda_abierta'`: el tipo debe tener `code == 'informal'` → si no, `debt_type_invalid`.
3. `currency_id` del país (`require_user_currency`) → `currency_not_available`.
4. `priority_level` existe y `!= 1` → `priority_level_invalid`.
5. `description.strip()` ≥ 8 → `description_invalid`.
6. `amount > 0` → `amount_invalid`.
7. Si `kind == 'deuda'` y `institution_id` con valor: existe en `institutions` y `country_code ==
   user.country_code` → si no, `institution_invalid`. (En `deuda_abierta` se ignora.)

**Validaciones por kind:**
- **`deuda`:**
  - `due_day` con valor → 1–31 (`due_day_invalid`).
  - `first_due_date` **obligatorio** → si falta, `debt_requires_schedule_or_date`.
  - **Cronograma** (`total_installments` con valor): `total_installments >= 1` (`installments_invalid`);
    `due_day` obligatorio (`debt_schedule_requires_due_day`).
  - **Pago único** (`total_installments` NULL): `due_day` debe ser NULL → si trae, `one_time_debt_inconsistent`.
  - `financing_rate`/`overdue_rate` con valor → `>= 0` (`rates_negative`).
- **`deuda_abierta`:** `due_day`, `total_installments`, `first_due_date`, `financing_rate`, `overdue_rate`
  deben ser NULL/ausentes → si alguno con valor, `open_debt_inconsistent`. `rates_add_vat` e `institution_id`
  se **ignoran**.

**Insert:** `is_monthly_recurring = False`; `origin_obligation_id = None`; `is_closed = False`;
`reviewed_at = None`; `review_findings = '[]'`; `user_acknowledged_at = None`; `is_ready = False`. Por kind:
- `deuda`: campos del body; `institution_id = body or None`; `rates_add_vat = body or True`;
  `shift_weekends = body or False`.
- `deuda_abierta`: `due_day/total_installments/first_due_date/financing_rate/overdue_rate/institution_id =
  None`; `rates_add_vat = False`; `shift_weekends = False`.

Luego orquestación §4. **Los findings no bloquean el alta:** el recurso se crea 201 aunque el reviewer deje
`is_ready = false` (el motor hace no-op, no materializa). El response trae `review_findings`/`is_ready`
reales.

---

## 6. `GET /debts` → 200

`SELECT` de `obligations` JOIN `obligation_types` WHERE `user_id` = token AND `obligation_kind IN
('deuda','deuda_abierta')`, ORDER BY `created_at DESC`. Incluye cerradas. Devuelve `{"debts": [DebtOut,
...]}` (puede ser `[]`).

---

## 7. `PATCH /debts/{id}` → 200

**Validaciones:**
1. Obligación con `id` y `user_id` = token; JOIN al tipo: si no existe / no es del usuario / kind no ∈
   {deuda, deuda_abierta} → `not_found` (404).
2. PATCH vacío: permitido (no-op; re-corre reviewer + motor).
3. Si `obligation_type_id` viene: existe y su kind **coincide con el kind actual** (`debt_type_invalid`). Si
   la fila es `deuda_abierta` y viene `obligation_type_id` → `debt_type_invalid` (no se puede cambiar).
4. Por campo presente: `currency_id` del país; `priority_level` ≠ 1 y existe; `description` ≥ 8 (no `null`);
   `amount > 0` (no `null`); `institution_id` con valor → existe y del país (`institution_invalid`);
   `due_day` 1–31 si con valor; `financing_rate`/`overdue_rate` con valor → `>= 0` (`rates_negative`);
   `rates_add_vat`/`shift_weekends`/`is_closed` bool (no `null` → `field_not_nullable`).
5. **Bloqueo de cronograma con pagos:** si el body intenta cambiar `first_due_date`, `total_installments` o
   `due_day` a un valor **distinto del actual** y la deuda tiene ≥1 `cash_flow_payment` (join por
   `source_type='deuda'` y `source_id={id}`) → **409 `debt_schedule_locked`**. Reenviar el mismo valor no
   cuenta. (Se chequea antes de aplicar el update.)
6. **Consistencia post-merge** por kind final (mismas reglas que POST §5):
   - `deuda`: `first_due_date` obligatorio (`debt_requires_schedule_or_date`); cronograma →
     `total_installments>=1` + `due_day` con valor; pago único → `due_day` NULL.
   - `deuda_abierta`: fechas/cuotas/tasas NULL (`open_debt_inconsistent`); `institution_id`/`rates_add_vat`
     ignorados (no se persisten).

**Update:** solo columnas presentes; `is_monthly_recurring`/`user_id`/`id`/`created_at`/`origin_obligation_id`
no se tocan; en `deuda_abierta` `institution_id` no se persiste aunque venga. `updated_at` natural. Luego
orquestación §4 (reviewer uniforme → motor del kind).

---

## 8. Decisiones, con su porqué

- **Router/servicio dedicados de debts:** el endpoint maneja 2 kinds + 2 sub-formas + lock de cronograma;
  un módulo propio lo aísla del de expenses.
- **Orquestación uniforme (reviewer siempre):** el `is_closed` lo dueña el reviewer (decisión de 6a); el
  endpoint no branchea. Motor elegido por kind (estable, no cambia en el PATCH).
- **Findings no bloquean el alta:** crear con `is_ready=false` es válido (201); el motor no materializa hasta
  resolver. Es el pipeline ReviewEngine→CashFlowEngine.
- **`debt_schedule_locked` (409):** reestructurar el cronograma con pagos descolocaría la historia; se
  bloquea en el endpoint antes de tocar nada. Mismo check de pagos que usará el DELETE (6c).
- **`institution_id`/`rates_add_vat` ignorados en `deuda_abierta`:** una deuda informal no tiene banco ni
  tasas; se silencian (no se rechaza), igual que Notion.
- **Validadores comunes replicados (no extraídos aún):** consistente con la decisión de mirror-then-extract;
  se consolidan en `obligation_common` tras 6c.

---

## 9. Tests (`tests/test_debts.py`)

Helper `_auth` y siembra: `priority_levels` (incluye nivel 1), `obligation_types` (deuda `code='prestamo'`;
deuda_abierta `code='informal'`; un gasto para el caso de kind inválido), `institutions` (una UY y, para el
caso negativo, una de otro país), currency. Consultas directas a `CashFlowEntry`/`CashFlowPayment`.

- **POST `deuda` cronograma:** 201, fila correcta, materializa cuotas (entries `source_type='deuda'` con
  tasas efectivas).
- **POST `deuda` pago único:** `total_installments`/`due_day` NULL, `first_due_date` con valor → 1 entry.
- **POST `deuda_abierta`:** tipo `informal`, 1 entry `event_date NULL`; `institution_id` que vino se ignora
  (queda NULL).
- **POST con findings:** `overdue_rate < financing_rate` → 201, `review_findings=['overdue_lower_than_financing']`,
  `is_ready=false`, **sin entries** materializadas.
- **POST errores:** kind gasto → `debt_type_invalid`; `deuda_abierta` con tipo no-informal →
  `debt_type_invalid`; moneda de otro país → `currency_not_available`; `priority_level=1` →
  `priority_level_invalid`; `description` corta → `description_invalid`; `amount<=0` → `amount_invalid`;
  `institution_id` de otro país → `institution_invalid`; `deuda` sin `first_due_date` →
  `debt_requires_schedule_or_date`; cronograma sin `due_day` → `debt_schedule_requires_due_day`;
  `total_installments=0` → `installments_invalid`; pago único con `due_day` → `one_time_debt_inconsistent`;
  tasa negativa → `rates_negative`; `deuda_abierta` con fecha/cuota/tasa → `open_debt_inconsistent`; sin
  token → 401.
- **GET:** lista deudas de ambos kinds del usuario, ordenada, incluye cerradas; `[]`; no devuelve gastos;
  401 sin token.
- **PATCH:** cambia `amount` (re-materializa, tasas se mantienen); cambia tasas (re-materializa efectivas);
  `is_closed=true` (reviewer short-circuit, `is_ready=true`, motor limpia futuras); convertir cronograma →
  pago único (sin pagos: OK); **`debt_schedule_locked`** al cambiar el cronograma con un pago presente;
  cambio de tipo a otro kind → `debt_type_invalid`; `deuda_abierta` con `obligation_type_id` →
  `debt_type_invalid`; `{id}` de otro usuario/kind → 404; patch vacío → 200.
- **Cierre con findings limpia futuras (el test que faltaba en 6a):** crear `deuda` lista (materializa
  cuotas), PATCH que introduce findings (`is_ready=false`, las cuotas siguen), luego PATCH `is_closed=true`
  → el reviewer fuerza `is_ready=true` → el motor **limpia las futuras**.

Regresión `pytest -q` verde.

---

## 10. Plan de implementación (orientativo)

Un slice (`feat/endpoints-debts`), 3 tasks: (1) error codes + schemas + `POST` + `GET` (+ router
registrado), (2) `PATCH` (incluye `debt_schedule_locked` y consistencia post-merge), (3) suite completa.
TDD por task.

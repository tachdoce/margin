# `POST` + `PATCH /incomes` (slice 2 de Ingresos) — Diseño

> Segundo slice de Ingresos: crear y modificar fuentes de ingreso, con toda la validación del modelo
> binario (recurrente infinito / duración fija) y los error codes propios. El *qué* del producto vive en
> Notion → Endpoints → Ingresos → POST incomes / PATCH incomes.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** tabla `incomes` (slice 1, en `main`), `get_current_user`, `income_types`, `currencies`.
- **Cierre:** rama `feat/incomes-post-patch`, **squash-merge** a `main`.

---

## 1. Alcance

- `POST /incomes` (201): crea una fuente de ingreso para el usuario autenticado.
- `PATCH /incomes/{id}` (200): modifica parcialmente una fuente vigente del usuario.
- Toda la validación de negocio + los error codes nuevos.

**Fuera de alcance:** `GET` y `DELETE` (slice 3). **Materialización** de `cash_flow_entries` en POST/PATCH,
soft-delete y reactivate → cuando exista el CashFlowEngine. (Notion menciona correr `materialize_income()`
tras el insert/update; en este slice ese paso **se omite**, no hay tablas `cash_flow_*` todavía.)

---

## 2. Decisión central: dónde vive la validación

**En la capa de servicio, lanzando `AppError` con los codes exactos de Notion** — no con constraints de
Pydantic. Notion define codes y mensajes específicos en español; Pydantic devolvería el genérico
`validation_failed`. Mismo patrón que `auth_service` (valida y lanza `AppError`).

Reparto:
- **Pydantic** valida solo lo **estructural/tipos**: que los requeridos estén presentes, que `amount` sea
  número, `payment_day`/`total_months` enteros, `first_income_date` una fecha `YYYY-MM-DD` válida. Un tipo
  mal formado → 422 `validation_failed` (handler global existente, formato `{code, message, errors[]}`).
- **Servicio** valida las **reglas de negocio** (existencia/visibilidad, rangos, forma binaria, currency del
  país) → 422 (o 404) con el code específico.

---

## 3. Contrato

### POST /incomes
**Body:** `income_type_id`, `currency_id`, `amount`, `description`, `is_monthly_recurring` (requeridos);
`payment_day`, `first_income_date`, `total_months`, `shift_weekends` (opcionales).

**201:** el income creado con la forma de `IncomeOut` (ver §5), `is_deleted = false`.

### PATCH /incomes/{id}
**Body:** todos los campos opcionales; semántica REST: campo **ausente** → no se toca; campo con **valor**
→ se actualiza; campo con **`null`** → se setea NULL (solo en los nullable: `payment_day`,
`first_income_date`, `total_months`). `description`, `amount`, `is_monthly_recurring`, `shift_weekends` **no**
aceptan `null`. `income_type_id`/`currency_id` tampoco.

**200:** el income modificado completo (forma de `IncomeOut`).

**Errores (ambos salvo donde se aclare):**
- 401 `unauthenticated`
- 404 `not_found` → "No encontrado." (solo PATCH: `{id}` no existe o no es del usuario o está soft-deleted)
- 422 `income_type_invalid` → "Tipo de ingreso no válido."
- 422 `currency_not_available` → "Esa moneda no está disponible. Elegí otra."
- 422 `description_invalid` → "La descripción es obligatoria y debe tener al menos 8 caracteres."
- 422 `amount_invalid` → "El monto debe ser mayor a 0."
- 422 `payment_day_invalid` → "El día de cobro debe estar entre 1 y 31."
- 422 `recurring_income_requires_payment_day` → "Un ingreso recurrente necesita un día de cobro."
- 422 `fixed_term_income_requires_dates` → "Un ingreso de duración fija necesita fecha de primer cobro y cantidad de meses."
- 422 `total_months_invalid` → "La cantidad de meses debe ser 1 o más."
- 422 `income_form_inconsistent` → "Las columnas no corresponden a la forma del ingreso (recurrente o duración fija)."

---

## 4. Modelo binario (regla compartida POST y PATCH)

El estado **final** del income debe ser exactamente una de dos formas:
- **Recurrente infinito** (`is_monthly_recurring = true`): `payment_day` con valor 1–31; `first_income_date`
  y `total_months` en NULL.
- **Duración fija** (`is_monthly_recurring = false`): `first_income_date` y `total_months` (≥ 1) con valor;
  `payment_day` en NULL. El cobro único es `total_months = 1`.

En PATCH la regla se evalúa sobre el **estado final** (fila mergeada con el patch); si queda inválido se
rechaza el patch **entero** (sin cambios parciales) — el frontend puede tener que mandar varios campos
juntos (ej. convertir recurrente → duración fija manda `is_monthly_recurring=false` + fechas + `payment_day=null`).

---

## 5. Schemas (`app/schemas/income.py`)

- **`IncomeCreate`**: tipos permisivos (`income_type_id: int`, `currency_id: int`, `amount: Decimal`,
  `description: str`, `is_monthly_recurring: bool`, `payment_day: int | None = None`,
  `first_income_date: date | None = None`, `total_months: int | None = None`,
  `shift_weekends: bool | None = None`). La validación de negocio la hace el servicio.
- **`IncomeUpdate`**: los 9 campos opcionales (default `None`). El servicio usa **`model_fields_set`** para
  saber cuáles vinieron (distinguir ausente de `null` explícito). No usar `getattr`/`.get()` plano.
- **`IncomeOut`**: `id, income_type_id, currency_id, amount, description, is_monthly_recurring, payment_day,
  first_income_date, total_months, shift_weekends, is_deleted`. `is_deleted` se deriva de `deleted_at is not
  None` (no se expone el timestamp). Se construye desde el modelo vía un helper (`IncomeOut.from_model` o
  equivalente).

---

## 6. Servicio (`app/services/income_service.py`)

`create_income(db, user, payload: IncomeCreate) -> Income` y
`update_income(db, user, income_id: UUID, payload: IncomeUpdate) -> Income`.

Helpers compartidos (DRY entre POST y PATCH):
- `_validate_income_type(db, income_type_id)` → existe en `income_types` y `visible = true`, si no `income_type_invalid`.
- `_validate_currency(db, user, currency_id)` → existe en `currencies` y `country_code == user.country_code`, si no `currency_not_available`.
- `_validate_amount(amount)` → `> 0`, si no `amount_invalid`.
- `_validate_description(description)` → `description.strip()` longitud ≥ 8, si no `description_invalid`.
- `_validate_payment_day(payment_day)` → si tiene valor, 1–31, si no `payment_day_invalid`.
- `_validate_form(is_monthly_recurring, payment_day, first_income_date, total_months)` → el modelo binario (§4),
  con `recurring_income_requires_payment_day` / `fixed_term_income_requires_dates` / `total_months_invalid` /
  `income_form_inconsistent`.

**`create_income`:** valida (income_type, currency, amount, description, payment_day si vino, form) →
inserta `Income` con `user_id` del token, `description.strip()`, `shift_weekends = payload.shift_weekends or
False`, nullables según la forma → `db.flush()` + `db.commit()` → devuelve la fila.

**`update_income`:** busca `Income` por `id` + `user_id` + `deleted_at IS NULL` (si no → `not_found` 404) →
calcula el estado final aplicando solo los campos de `model_fields_set` → valida los campos presentes y la
forma sobre el estado final (si inválido, no persiste nada) → asigna los campos → `updated_at = now()` →
`commit` → devuelve.

El servicio no conoce HTTP; lanza `AppError`. El router es finito.

---

## 7. Router (`app/routers/incomes.py`) + `main.py`

`router = APIRouter(tags=["incomes"])` con:
- `POST /incomes` → 201, `Depends(get_current_user)`, body `IncomeCreate`, devuelve `IncomeOut`.
- `PATCH /incomes/{id}` → 200, `Depends(get_current_user)`, body `IncomeUpdate`, devuelve `IncomeOut`.

Montar `incomes.router` en `app/main.py` (orden alfabético en el import: `auth, bootstrap, countries, health, incomes`).

---

## 8. Error codes nuevos (al enum `ErrorCode` en `app/core/errors.py`)

`income_type_invalid` (422), `currency_not_available` (422), `description_invalid` (422), `amount_invalid`
(422), `payment_day_invalid` (422), `recurring_income_requires_payment_day` (422),
`fixed_term_income_requires_dates` (422), `total_months_invalid` (422), `income_form_inconsistent` (422),
`not_found` (404). Mensajes: los de la §3.

---

## 9. Testing (TDD, `tests/test_incomes.py`)

`client` + `db_session` + `seed_uy`. Setup: sembrar un `income_type` visible (id 1) + uno oculto
(`visible=false`), `currencies` (UY id 1 + otra de país AR para el rechazo cross-país), y registrar un
usuario (token vía `POST /auth/register`).

**POST:**
- feliz recurrente (201, `is_deleted=false`, `payment_day` set, fechas null).
- feliz duración fija (`first_income_date`+`total_months`, `payment_day` null).
- `user_id` se toma del token (no del body aunque se mande otro).
- cada error: `income_type_invalid` (id inexistente y oculto), `currency_not_available` (otra país),
  `description_invalid` (< 8 tras trim), `amount_invalid` (0 / negativo), `payment_day_invalid` (0 / 32),
  `recurring_income_requires_payment_day`, `fixed_term_income_requires_dates`, `total_months_invalid` (0),
  `income_form_inconsistent` (recurrente con fechas / fija con payment_day).
- sin token → 401.

**PATCH:**
- merge parcial (cambiar solo `payment_day`).
- `null` explícito borra un nullable; campo ausente no se toca (distinción `model_fields_set`).
- consistencia post-merge: convertir recurrente → duración fija (varios campos juntos) OK; mandar solo
  `first_income_date` (deja estado inválido) → `income_form_inconsistent`/`fixed_term_income_requires_dates`.
- 404 con `{id}` ajeno o inexistente.
- sin token → 401.

---

## 10. Decisiones, con su porqué

- **Validación en servicio con codes propios:** contrato de errores estable y en español, igual que el
  resto del backend; Pydantic queda para tipos.
- **`model_fields_set` en PATCH:** única forma de distinguir "no mandes el campo" de "ponelo en NULL", que
  es semántica del contrato.
- **Materialización omitida:** no existen las tablas `cash_flow_*`; se cablea cuando llegue el CashFlowEngine
  (el insert/update queda igual, solo se le suma la llamada). El income se crea/edita sin efecto aguas abajo
  por ahora, que es lo esperado en este slice.
- **`shift_weekends` default false en el backend:** la tabla no tiene default (regla del proyecto); lo fija
  el servicio si no vino.

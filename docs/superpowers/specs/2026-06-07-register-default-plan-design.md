# Crear el plan default al registrarse — Diseño

> Extiende `POST /auth/register` para que cree el **plan default** del usuario en la misma transacción.
> Era el "diferido" del registro: ahora que existe la tabla `plans`, se implementa. El *qué* vive en
> Notion → Endpoints → Usuarios → POST register, y BD → Flujo de dinero → plans.

- **Fecha:** 2026-06-07
- **Estado:** aprobado para implementar
- **Depende de:** `users`/`auth_identities` (auth ya hecho), tabla `plans` (en `main`), `currencies` (seed).
- **Cierre:** rama `feat/register-default-plan`, **squash-merge** a `main`.

---

## 1. Alcance

- Al registrarse un usuario, crear también su **plan default** en la **misma transacción** que `users` +
  `auth_identities`. Si algo falla, rollback total (no queda usuario sin plan ni plan sin usuario).
- El **contrato de `POST /auth/register` no cambia**: sigue devolviendo `{user, token}`. El plan no se
  expone en la respuesta.

**Fuera de alcance:** endpoints de plans (GET/POST/PATCH/DELETE), validación de objetivo/dial, y la
materialización a `cash_flow_entries` (engine). Solo se crea la fila del plan default.

---

## 2. Arquitectura por capas

- **Nuevo `app/services/plan_service.py`** con `create_default_plan(db, user) -> Plan`. Es lógica del
  dominio *plans* (no de auth) y es donde vivirán los futuros endpoints de plans. No hace `commit`: lo
  agrega a la sesión y deja que el caller (register) controle la transacción.
- **`auth_service.register_user`** lo invoca **después** de crear user + identity y **antes** del `commit`
  que ya tiene. Así todo entra en una transacción.

---

## 3. El plan default (valores de Notion → POST register)

`create_default_plan(db, user)` inserta en `plans`:

| columna | valor |
|---|---|
| user_id | `user.id` |
| name | `"Mi plan actual"` |
| is_default | `True` |
| is_engine_generated | `False` |
| selected_at | `now()` (UTC) — el default nace activo |
| dial_amount | `Decimal("0")` |
| dial_currency_id | id de la `currencies` con `is_legal_tender = true` AND `country_code = user.country_code` |
| goal_kind / goal_amount / goal_currency_id | `None` (sin objetivo) |

---

## 4. Dependencia: moneda de curso legal

`create_default_plan` busca la moneda principal del país del usuario:
`select(Currency).where(Currency.country_code == user.country_code, Currency.is_legal_tender.is_(True))`.

- **Prod:** existe siempre (sembrada por migración: Peso UY `is_legal_tender=true`).
- **Asunción / borde:** es un prerrequisito del sistema (cada país soportado tiene su moneda de curso legal
  sembrada). Si no existiera, sería un error de configuración del backend, no un error de negocio del
  usuario; no se agrega un error code nuevo. (En la práctica no ocurre porque el seed corre en la migración.)

---

## 5. Tests

- **Fixture nuevo en `conftest.py`:** `seed_uy_currency(db_session, seed_uy)` — reusa `seed_uy` (país UY) y
  suma `Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True)`.
  No se toca `seed_uy` (sembrar la currency ahí chocaría con tests que ya siembran `Currency(id=1)`).
- **Tests de auth (`test_auth_register.py`, `test_auth_login.py`):** cambian la fixture `seed_uy` →
  `seed_uy_currency` (para que el registro pueda crear el plan).
- **Test nuevo en `test_auth_register.py`:** tras `POST /auth/register`, consultar `plans` del usuario y
  verificar que hay **exactamente 1**, con `is_default=True`, `is_engine_generated=False`,
  `name="Mi plan actual"`, `dial_amount == Decimal("0")` (o `0`), `dial_currency_id == 1` (la de curso
  legal sembrada), `goal_kind/goal_amount/goal_currency_id` en NULL, y `selected_at` no nulo.
- Regresión: `pytest -q` verde.

---

## 6. Decisiones, con su porqué

- **`plan_service.py` nuevo (no inline en auth):** la creación del plan es dominio *plans*; mantener
  `auth_service` enfocado y dejar el módulo donde crecerán los endpoints de plans. Split natural.
- **El servicio no hace `commit`:** lo controla `register_user`, que ya maneja la transacción (un solo
  punto de commit/rollback para user + identity + plan).
- **Moneda derivada del país, no del body:** igual criterio que `country_code` fijo en `'UY'` en el MVP.
- **Fixture `seed_uy_currency` aislado:** resuelve la dependencia de los tests de auth sin tocar el resto
  del harness ni los tests que ya siembran sus propios maestros.

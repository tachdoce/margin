# Tipos `deuda` y `tarjetazo` en plan_movements — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar dos kinds de `plan_movements` — `deuda` (endpoint genérico) y `tarjetazo` (endpoint dedicado desde una tarjeta) — que se materializan como Préstamo pero sin la entrada de capital (solo cuotas), más un endpoint de borrado masivo de `tarjetazo`.

**Architecture:** El row es un `plan_movement` "tipo deuda": `principal_amount=0`, sin entry de entrada, solo cuotas de salida con tasas. `deuda` se crea por el POST genérico (el usuario manda cuotas+tasas); `tarjetazo` por un POST dedicado que deriva tasas, fecha del primer pago y descripción desde una `credit_card` (snapshot, sin FK). Ambos comparten la rama de materialización `DEBT_KINDS`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Postgres 16, pytest. `Decimal` siempre (nunca float).

**Spec:** `docs/superpowers/specs/2026-06-12-tipos-deuda-y-tarjetazo-plan-movements-design.md`

**Contexto base para el implementador:**
- Trabajar desde `backend/` con venv: `cd backend && source .venv/bin/activate`.
- Tests: `pytest -q` (base `margin_test`). Los tests arman la base con `Base.metadata.create_all()` (no corren migraciones) y siembran con fixtures (`tests/conftest.py`).
- Errores: lanzar `AppError(ErrorCode.x)` desde el servicio (nunca `HTTPException`).
- Head actual de Alembic: `d2a2d9f5a6e3` (verificar con `alembic heads`).

---

### Task 1: Enum `deuda`/`tarjetazo` (modelo + migración + base de tests)

**Files:**
- Modify: `app/models/plan_movement.py:18`
- Create: `alembic/versions/<rev>_add_deuda_tarjetazo_to_plan_movement_kind.py`

- [ ] **Step 1: Agregar los valores al Enum del modelo**

En `app/models/plan_movement.py:18`, cambiar:
```python
        Enum("ingreso", "deuda_informal", "prestamo", name="plan_movement_kind"), nullable=False
```
por:
```python
        Enum(
            "ingreso", "deuda_informal", "prestamo", "deuda", "tarjetazo",
            name="plan_movement_kind",
        ),
        nullable=False,
```

- [ ] **Step 2: Recrear la base de tests para que el enum tome los valores nuevos**

`create_all` NO altera un tipo enum ya existente en `margin_test`. Recrear la base (no pierde nada: los tests siembran con fixtures):
```bash
dropdb margin_test && createdb margin_test
```
Expected: sin salida (ok). El primer `pytest` reconstruye las tablas desde el modelo con los 5 valores.

- [ ] **Step 3: Generar el skeleton de la migración**

```bash
alembic revision -m "add deuda tarjetazo to plan_movement_kind"
```
Expected: crea `alembic/versions/<rev>_add_deuda_tarjetazo_to_plan_movement_kind.py` con `down_revision = 'd2a2d9f5a6e3'`. Verificar ese `down_revision`.

- [ ] **Step 4: Escribir upgrade/downgrade**

Reemplazar `upgrade`/`downgrade` (conservando los identificadores que generó Alembic):
```python
def upgrade() -> None:
    op.execute("ALTER TYPE plan_movement_kind ADD VALUE IF NOT EXISTS 'deuda'")
    op.execute("ALTER TYPE plan_movement_kind ADD VALUE IF NOT EXISTS 'tarjetazo'")


def downgrade() -> None:
    # Postgres no permite DROP VALUE: se recrea el tipo sin deuda/tarjetazo.
    # Falla si existen filas con esos kinds (hay que borrarlas antes de revertir).
    op.execute("ALTER TYPE plan_movement_kind RENAME TO plan_movement_kind_old")
    op.execute("CREATE TYPE plan_movement_kind AS ENUM ('ingreso', 'deuda_informal', 'prestamo')")
    op.execute(
        "ALTER TABLE plan_movements ALTER COLUMN kind TYPE plan_movement_kind "
        "USING kind::text::plan_movement_kind"
    )
    op.execute("DROP TYPE plan_movement_kind_old")
```

- [ ] **Step 5: Aplicar la migración a la base dev**

```bash
alembic upgrade head
```
Expected: `Running upgrade d2a2d9f5a6e3 -> <rev>, add deuda tarjetazo to plan_movement_kind`.

- [ ] **Step 6: Commit**

```bash
git add app/models/plan_movement.py alembic/versions/*_add_deuda_tarjetazo_to_plan_movement_kind.py
git commit -m "feat: enum plan_movement_kind suma deuda y tarjetazo"
```

---

### Task 2: `DEBT_KINDS` + materialización (cuotas sin entrada)

**Files:**
- Modify: `app/services/cash_flow/plan_movements.py`
- Test: `tests/test_cashflow_engine_plan_movements.py`

- [ ] **Step 1: Escribir el test que falla**

En `tests/test_cashflow_engine_plan_movements.py`, agregar (usa el helper `_seed_movement` y `_entries` ya existentes en el archivo):
```python
def test_deuda_solo_cuotas_sin_entrada(db_session, seed_uy):
    mov = _seed_movement(
        db_session,
        kind="deuda",
        principal_amount=Decimal("0.00"),
        start_date=date(2026, 8, 1),
        installment_amount=Decimal("5000.00"),
        installment_start_date=date(2026, 8, 1),
        total_installments=3,
        financing_rate=Decimal("72.00"),
        overdue_rate=Decimal("85.00"),
        rates_add_vat=True,
    )
    materialize_plan_movement(db_session, mov.id, today=date(2026, 7, 1), horizon=date(2027, 12, 31))
    entries = _entries(db_session, mov)
    # 3 cuotas de salida, ninguna entrada
    assert len(entries) == 3
    assert all(e.source_type == "plan_movimiento" for e in entries)
    assert all(e.is_income is False for e in entries)
    assert all(e.amount == Decimal("5000.00") for e in entries)
    # tasa efectiva con IVA 22%: 72 * 1.22 = 87.84
    assert entries[0].financing_rate == Decimal("87.84")
```

- [ ] **Step 2: Correr el test (falla)**

Run: `pytest tests/test_cashflow_engine_plan_movements.py::test_deuda_solo_cuotas_sin_entrada -q`
Expected: FAIL (kind `deuda` no produce targets → `len(entries) == 0`).

- [ ] **Step 3: Definir `DEBT_KINDS` y la rama de materialización**

En `app/services/cash_flow/plan_movements.py`, después de los imports y antes de `HORIZON`, agregar:
```python
# deuda: deuda en cuotas, sin entrada de capital (POST genérico).
# tarjetazo: igual que deuda, pero modela una compra de impulso desde una tarjeta;
#   se crea por POST .../movements/tarjetazos y se puede borrar en bloque
#   (DELETE .../movements/tarjetazos).
DEBT_KINDS = ("deuda", "tarjetazo")
```
En `_target_entries`, después del bloque `elif kind == "prestamo":` (que termina en su loop de cuotas), agregar:
```python
    elif kind in DEBT_KINDS:
        # como préstamo pero SIN la entrada de capital: solo cuotas de salida
        vat_rate = db.get(Country, user.country_code).vat_rate
        fin = effective_rate(movement.financing_rate, movement.rates_add_vat, vat_rate)
        over = effective_rate(movement.overdue_rate, movement.rates_add_vat, vat_rate)
        for ed in _monthly_dates(movement.installment_start_date, movement.total_installments, horizon, shift=True):
            if today <= ed <= horizon:
                targets.append(
                    _target("plan_movimiento", ed, False, movement.installment_amount, fin, over)
                )
```

- [ ] **Step 4: Correr el test (pasa)**

Run: `pytest tests/test_cashflow_engine_plan_movements.py::test_deuda_solo_cuotas_sin_entrada -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/cash_flow/plan_movements.py tests/test_cashflow_engine_plan_movements.py
git commit -m "feat: materializa deuda/tarjetazo como cuotas sin entrada (DEBT_KINDS)"
```

---

### Task 3: `deuda` por el endpoint genérico

**Files:**
- Modify: `app/schemas/plan_movement.py` (Create: `principal_amount`, `start_date` opcionales)
- Modify: `app/services/plan_movement_service.py`
- Test: `tests/test_plan_movements.py`

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_plan_movements.py`, agregar un helper y tests (siguen el estilo de `_prestamo`):
```python
def _deuda(**over):
    body = {
        "kind": "deuda",
        "currency_id": 1,
        "installment_amount": "5000.00",
        "installment_start_date": "2026-08-01",
        "total_installments": 6,
        "financing_rate": "72.00",
        "overdue_rate": "85.00",
        "rates_add_vat": True,
    }
    body.update(over)
    return body


def test_create_deuda_fija_backend(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_deuda(), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "deuda"
    assert body["principal_amount"] == "0.00"
    assert body["start_date"] == "2026-08-01"      # = installment_start_date
    assert body["income_duration_months"] is None
    assert body["total_installments"] == 6


def test_create_deuda_rechaza_income_duration(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_deuda(income_duration_months=3), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "movement_fields_invalid"


def test_create_deuda_exige_cuotas(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(
        f"/plans/{plan_id}/movements",
        json={"kind": "deuda", "currency_id": 1, "total_installments": 6},
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "installments_invalid"


def test_create_tarjetazo_por_generico_rechazado(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.post(f"/plans/{plan_id}/movements", json=_deuda(kind="tarjetazo"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "kind_invalid"
```
(El handler de `AppError` rinde el error plano `{"code": ..., "message": ...}` — ver `app/core/errors.py:96`.)

- [ ] **Step 2: Correr los tests (fallan)**

Run: `pytest tests/test_plan_movements.py -q`
Expected: FAIL en los nuevos (deuda no soportada; el schema aún exige `principal_amount`/`start_date`).

- [ ] **Step 3: Hacer opcionales `principal_amount` y `start_date` en el Create**

En `app/schemas/plan_movement.py`, en `PlanMovementCreate`, cambiar:
```python
    principal_amount: Decimal
    start_date: date
```
por:
```python
    principal_amount: Decimal | None = None
    start_date: date | None = None
```
(No tocar `PlanMovementUpdate` ni `PlanMovementOut`.)

- [ ] **Step 4: Soportar `deuda` en el servicio**

En `app/services/plan_movement_service.py`:

(a) Import de `DEBT_KINDS` y `MOVEMENT_KINDS` con `deuda` (sin `tarjetazo`). Cambiar:
```python
from app.services.cash_flow.plan_movements import materialize_plan_movement
```
por:
```python
from app.services.cash_flow.plan_movements import DEBT_KINDS, materialize_plan_movement
```
y:
```python
MOVEMENT_KINDS = ("ingreso", "deuda_informal", "prestamo")
```
por:
```python
MOVEMENT_KINDS = ("ingreso", "deuda_informal", "prestamo", "deuda")
```

(b) En `_check_foreign_fields`, agregar la rama (después de `elif kind == "prestamo":`):
```python
    elif kind in DEBT_KINDS:
        if any(f in present for f in INCOME_FIELD):
            raise AppError(ErrorCode.movement_fields_invalid)
```

(c) Reemplazar el bloque de `create_movement` que valida `principal_amount` y arma la fila. Cambiar:
```python
    require_user_currency(db, user, payload.currency_id)
    if payload.principal_amount is None or payload.principal_amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="principal_amount")

    present = {f: getattr(payload, f) for f in OPTIONAL_FIELDS if getattr(payload, f) is not None}
    _check_foreign_fields(payload.kind, present)

    is_loan = payload.kind == "prestamo"
    if is_loan:
        _validate_installments(payload.installment_amount, payload.installment_start_date, payload.total_installments)

    movement = PlanMovement(
        plan_id=plan.id,
        kind=payload.kind,
        currency_id=payload.currency_id,
        description=payload.description,
        principal_amount=payload.principal_amount,
        start_date=payload.start_date,
        income_duration_months=1 if is_loan else payload.income_duration_months,
        installment_amount=payload.installment_amount if is_loan else None,
        installment_start_date=payload.installment_start_date if is_loan else None,
        total_installments=payload.total_installments if is_loan else None,
        financing_rate=payload.financing_rate if is_loan else None,
        overdue_rate=payload.overdue_rate if is_loan else None,
        rates_add_vat=payload.rates_add_vat if payload.rates_add_vat is not None else True,
    )
```
por:
```python
    require_user_currency(db, user, payload.currency_id)

    is_loan = payload.kind == "prestamo"
    is_debt = payload.kind in DEBT_KINDS
    uses_installments = is_loan or is_debt

    if not is_debt:
        if payload.principal_amount is None or payload.principal_amount <= 0:
            raise AppError(ErrorCode.amount_invalid, field="principal_amount")
        if payload.start_date is None:
            raise AppError(ErrorCode.movement_fields_invalid)

    present = {f: getattr(payload, f) for f in OPTIONAL_FIELDS if getattr(payload, f) is not None}
    _check_foreign_fields(payload.kind, present)

    if uses_installments:
        _validate_installments(payload.installment_amount, payload.installment_start_date, payload.total_installments)

    movement = PlanMovement(
        plan_id=plan.id,
        kind=payload.kind,
        currency_id=payload.currency_id,
        description=payload.description,
        principal_amount=Decimal(0) if is_debt else payload.principal_amount,
        start_date=payload.installment_start_date if is_debt else payload.start_date,
        income_duration_months=(1 if is_loan else (None if is_debt else payload.income_duration_months)),
        installment_amount=payload.installment_amount if uses_installments else None,
        installment_start_date=payload.installment_start_date if uses_installments else None,
        total_installments=payload.total_installments if uses_installments else None,
        financing_rate=payload.financing_rate if uses_installments else None,
        overdue_rate=payload.overdue_rate if uses_installments else None,
        rates_add_vat=payload.rates_add_vat if payload.rates_add_vat is not None else True,
    )
```

(d) En `update_movement`, cambiar la validación final de cuotas y re-fijar `start_date`. Cambiar:
```python
    # estado final de préstamo: las cuotas deben quedar consistentes
    if movement.kind == "prestamo":
        _validate_installments(
            movement.installment_amount, movement.installment_start_date, movement.total_installments
        )
```
por:
```python
    # estado final con cuotas (préstamo y deudas): deben quedar consistentes
    if movement.kind == "prestamo" or movement.kind in DEBT_KINDS:
        _validate_installments(
            movement.installment_amount, movement.installment_start_date, movement.total_installments
        )
    # en las deudas, start_date sigue al installment_start_date
    if movement.kind in DEBT_KINDS:
        movement.start_date = movement.installment_start_date
```

- [ ] **Step 5: Correr los tests (pasan)**

Run: `pytest tests/test_plan_movements.py -q`
Expected: PASS (los nuevos y los existentes).

- [ ] **Step 6: Commit**

```bash
git add app/schemas/plan_movement.py app/services/plan_movement_service.py tests/test_plan_movements.py
git commit -m "feat: deuda en plan_movements (POST genérico, sin entrada de capital)"
```

---

### Task 4: `tarjetazo` por endpoint dedicado (desde tarjeta)

**Files:**
- Modify: `app/schemas/plan_movement.py` (nuevo `TarjetazoCreate`)
- Modify: `app/services/plan_movement_service.py` (`_first_payment_date`, `create_tarjetazo`)
- Modify: `app/routers/plan_movements.py` (POST dedicado)
- Test: `tests/test_plan_movements.py`

- [ ] **Step 1: Test unitario de `_first_payment_date` (falla)**

En `tests/test_plan_movements.py`, agregar (import al tope del archivo:
`from app.services.plan_movement_service import _first_payment_date`):
```python
def test_first_payment_date_antes_del_cierre():
    # cierre 20, vencimiento 30; compra el 20-jun → 30-jun
    assert _first_payment_date(20, 30, date(2026, 6, 20)) == date(2026, 6, 30)


def test_first_payment_date_despues_del_cierre():
    # compra el 21-jun → 30-jul
    assert _first_payment_date(20, 30, date(2026, 6, 21)) == date(2026, 7, 30)


def test_first_payment_date_due_menor_que_closing():
    # cierre 25, vencimiento 5: la compra del 10-jun entra al cierre 25-jun y vence 5-jul
    assert _first_payment_date(25, 5, date(2026, 6, 10)) == date(2026, 7, 5)
```

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_plan_movements.py -q -k first_payment_date`
Expected: FAIL (ImportError: `_first_payment_date` no existe).

- [ ] **Step 3: Implementar `_first_payment_date`**

En `app/services/plan_movement_service.py`, agregar `import calendar` y `from datetime import date` al tope (si `date` no está importado), y la función:
```python
def _first_payment_date(closing_day: int, due_day: int, today: date) -> date:
    """Fecha del primer pago de una compra hecha hoy: entra al cierre de este mes
    si hoy <= closing_day, si no al del mes siguiente; vence el mismo mes del cierre
    si due_day >= closing_day, si no el mes siguiente."""
    last = calendar.monthrange(today.year, today.month)[1]
    closing_this = date(today.year, today.month, min(closing_day, last))
    if today <= closing_this:
        cy, cm = today.year, today.month
    else:
        cy, cm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    if due_day >= closing_day:
        dy, dm = cy, cm
    else:
        dy, dm = (cy + 1, 1) if cm == 12 else (cy, cm + 1)
    dlast = calendar.monthrange(dy, dm)[1]
    return date(dy, dm, min(due_day, dlast))
```

- [ ] **Step 4: Correr (pasa)**

Run: `pytest tests/test_plan_movements.py -q -k first_payment_date`
Expected: PASS.

- [ ] **Step 5: Test de creación de tarjetazo vía API (falla)**

En `tests/test_plan_movements.py`, agregar imports (al tope del archivo; `date`, `Decimal`, `select` ya están importados) y un helper que inserta una tarjeta para el usuario autenticado:
```python
from app.models.credit_card import CreditCard
from app.models.currency import Currency
from app.models.institution import Institution
from app.models.credit_card_network import CreditCardNetwork
from app.models.user import User


def _seed_card(db_session, email, **over):
    """Inserta una credit_card para el usuario `email`. Requiere institución y red sembradas."""
    db_session.add_all([
        Institution(id=1, country_code="UY", name="Scotiabank", visible=True),
        CreditCardNetwork(id=1, country_code="UY", code="visa", name="Visa"),
    ])
    db_session.flush()
    user = db_session.execute(select(User).where(User.email == email)).scalar_one()
    fields = dict(
        user_id=user.id,
        institution_id=1,
        card_network_id=1,
        current_limit=Decimal("100000.00"),
        closing_day=20,
        due_day=30,
        financing_rate_local=Decimal("72.00"),
        overdue_rate_local=Decimal("85.00"),
        financing_rate_usd=Decimal("40.00"),
        overdue_rate_usd=Decimal("50.00"),
        rates_add_vat=True,
        review_findings="",
        is_ready=True,
    )
    fields.update(over)
    card = CreditCard(**fields)
    db_session.add(card)
    db_session.flush()
    return card
```
Y los tests (necesitan Peso id1 + Dólar id3 + una moneda no-tarjeta id4; `seed_uy` da el país):
```python
def _seed_card_currencies(db_session):
    db_session.add_all([
        Currency(id=1, country_code="UY", name="Peso", is_legal_tender=True, allowed_in_credit_card=True),
        Currency(id=3, country_code="UY", name="Dólar", is_legal_tender=False, allowed_in_credit_card=True),
        Currency(id=4, country_code="UY", name="UI", is_legal_tender=False, allowed_in_credit_card=False),
    ])
    db_session.flush()


def test_create_tarjetazo_local(client, db_session, seed_uy):
    _seed_card_currencies(db_session)
    headers = _auth(client)
    card = _seed_card(db_session, "u@b.com")
    plan_id = _plan(client, headers)
    resp = client.post(
        f"/plans/{plan_id}/movements/tarjetazos",
        json={"installment_amount": "3000.00", "total_installments": 6,
              "credit_card_id": str(card.id), "currency_id": 1},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "tarjetazo"
    assert body["principal_amount"] == "0.00"
    assert body["description"] == "Scotiabank"
    assert body["financing_rate"] == "72.00"      # par local
    assert body["overdue_rate"] == "85.00"
    assert body["rates_add_vat"] is True
    assert body["start_date"] == body["installment_start_date"]


def test_create_tarjetazo_usd_usa_par_usd(client, db_session, seed_uy):
    _seed_card_currencies(db_session)
    headers = _auth(client)
    card = _seed_card(db_session, "u@b.com")
    plan_id = _plan(client, headers)
    resp = client.post(
        f"/plans/{plan_id}/movements/tarjetazos",
        json={"installment_amount": "100.00", "total_installments": 3,
              "credit_card_id": str(card.id), "currency_id": 3},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["financing_rate"] == "40.00"   # par usd


def test_create_tarjetazo_moneda_no_tarjeta(client, db_session, seed_uy):
    _seed_card_currencies(db_session)
    headers = _auth(client)
    card = _seed_card(db_session, "u@b.com")
    plan_id = _plan(client, headers)
    resp = client.post(
        f"/plans/{plan_id}/movements/tarjetazos",
        json={"installment_amount": "100.00", "total_installments": 3,
              "credit_card_id": str(card.id), "currency_id": 4},
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "currency_not_available"


def test_create_tarjetazo_tarjeta_ajena(client, db_session, seed_uy):
    _seed_card_currencies(db_session)
    headers = _auth(client)
    card = _seed_card(db_session, "u@b.com")
    headers2 = _auth(client, email="otro@b.com")
    plan_id2 = _plan(client, headers2)
    resp = client.post(
        f"/plans/{plan_id2}/movements/tarjetazos",
        json={"installment_amount": "100.00", "total_installments": 3,
              "credit_card_id": str(card.id), "currency_id": 1},
        headers=headers2,
    )
    assert resp.status_code == 404
```

- [ ] **Step 6: Correr (falla)**

Run: `pytest tests/test_plan_movements.py -q -k tarjetazo`
Expected: FAIL (no existe el schema ni la ruta).

- [ ] **Step 7: Schema `TarjetazoCreate`**

En `app/schemas/plan_movement.py`, agregar (con `import uuid` ya presente):
```python
class TarjetazoCreate(BaseModel):
    installment_amount: Decimal
    total_installments: int
    credit_card_id: uuid.UUID
    currency_id: int
```

- [ ] **Step 8: `create_tarjetazo` en el servicio**

En `app/services/plan_movement_service.py`, agregar imports:
```python
from app.models.credit_card import CreditCard
from app.models.currency import Currency
from app.models.institution import Institution
from app.schemas.plan_movement import PlanMovementCreate, PlanMovementUpdate, TarjetazoCreate
```
(extender el import existente de `app.schemas.plan_movement` con `TarjetazoCreate`).
Y la función:
```python
def create_tarjetazo(
    db: Session, user: User, plan_id: uuid.UUID, payload: TarjetazoCreate, today: date | None = None
) -> PlanMovement:
    if today is None:
        today = date.today()
    plan = _get_owned_plan(db, user, plan_id)
    if plan.is_default:
        raise AppError(ErrorCode.default_plan_no_movements)

    currency = require_user_currency(db, user, payload.currency_id)
    if not currency.allowed_in_credit_card:
        raise AppError(ErrorCode.currency_not_available, field="currency_id")

    card = db.execute(
        select(CreditCard).where(CreditCard.id == payload.credit_card_id, CreditCard.user_id == user.id)
    ).scalar_one_or_none()
    if card is None:
        raise AppError(ErrorCode.not_found)

    first_payment = _first_payment_date(card.closing_day, card.due_day, today)
    _validate_installments(payload.installment_amount, first_payment, payload.total_installments)

    if currency.is_legal_tender:
        fin, over = card.financing_rate_local, card.overdue_rate_local
    else:
        fin, over = card.financing_rate_usd, card.overdue_rate_usd
    institution = db.get(Institution, card.institution_id)

    movement = PlanMovement(
        plan_id=plan.id,
        kind="tarjetazo",
        currency_id=payload.currency_id,
        description=institution.name,
        principal_amount=Decimal(0),
        start_date=first_payment,
        income_duration_months=None,
        installment_amount=payload.installment_amount,
        installment_start_date=first_payment,
        total_installments=payload.total_installments,
        financing_rate=fin,
        overdue_rate=over,
        rates_add_vat=card.rates_add_vat,
    )
    db.add(movement)
    db.flush()
    materialize_plan_movement(db, movement.id, today=today)
    db.commit()
    db.refresh(movement)
    return movement
```
(`require_user_currency` devuelve la `Currency`; ya está importado.)

- [ ] **Step 9: Ruta POST dedicada**

En `app/routers/plan_movements.py`, extender el import de schemas con `TarjetazoCreate` y agregar la ruta **antes** del `@router.patch("/plans/{plan_id}/movements/{movement_id}", ...)`:
```python
@router.post(
    "/plans/{plan_id}/movements/tarjetazos",
    response_model=PlanMovementOut,
    status_code=status.HTTP_201_CREATED,
)
def create_tarjetazo(
    plan_id: uuid.UUID,
    payload: TarjetazoCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanMovementOut:
    return PlanMovementOut.from_model(plan_movement_service.create_tarjetazo(db, user, plan_id, payload))
```

- [ ] **Step 10: Correr (pasa)**

Run: `pytest tests/test_plan_movements.py -q`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add app/schemas/plan_movement.py app/services/plan_movement_service.py app/routers/plan_movements.py tests/test_plan_movements.py
git commit -m "feat: endpoint POST tarjetazos (deuda desde tarjeta, snapshot)"
```

---

### Task 5: Borrado masivo de `tarjetazo`

**Files:**
- Modify: `app/services/plan_movement_service.py` (`delete_tarjetazos`)
- Modify: `app/routers/plan_movements.py` (DELETE dedicado)
- Test: `tests/test_plan_movements.py`

- [ ] **Step 1: Test (falla)**

En `tests/test_plan_movements.py`:
```python
def test_delete_tarjetazos_borra_solo_tarjetazos(client, db_session, seed_uy):
    _seed_card_currencies(db_session)
    headers = _auth(client)
    card = _seed_card(db_session, "u@b.com")
    plan_id = _plan(client, headers)
    # 2 tarjetazos + 1 deuda
    for _ in range(2):
        client.post(f"/plans/{plan_id}/movements/tarjetazos",
                    json={"installment_amount": "100.00", "total_installments": 3,
                          "credit_card_id": str(card.id), "currency_id": 1}, headers=headers)
    client.post(f"/plans/{plan_id}/movements", json=_deuda(), headers=headers)

    resp = client.delete(f"/plans/{plan_id}/movements/tarjetazos", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2}

    remaining = client.get(f"/plans/{plan_id}/movements", headers=headers).json()
    assert [m["kind"] for m in remaining] == ["deuda"]


def test_delete_tarjetazos_sin_ninguno(client, db_session, seed_uy_currency):
    headers = _auth(client)
    plan_id = _plan(client, headers)
    resp = client.delete(f"/plans/{plan_id}/movements/tarjetazos", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0}
```

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_plan_movements.py -q -k delete_tarjetazos`
Expected: FAIL (404/405: la ruta no existe).

- [ ] **Step 3: `delete_tarjetazos` en el servicio**

En `app/services/plan_movement_service.py` (`delete` y `select` ya importados):
```python
def delete_tarjetazos(db: Session, user: User, plan_id: uuid.UUID) -> int:
    """Borra todos los plan_movements kind=tarjetazo del plan y sus cash_flow_entries.
    Devuelve la cantidad borrada. No corre el motor."""
    _get_owned_plan(db, user, plan_id)
    ids = list(
        db.execute(
            select(PlanMovement.id).where(
                PlanMovement.plan_id == plan_id, PlanMovement.kind == "tarjetazo"
            )
        ).scalars()
    )
    if not ids:
        return 0
    db.execute(
        delete(CashFlowEntry).where(
            CashFlowEntry.source_type.in_(("plan_movimiento", "plan_movimiento_entrada")),
            CashFlowEntry.source_id.in_(ids),
        )
    )
    db.execute(delete(PlanMovement).where(PlanMovement.id.in_(ids)))
    db.commit()
    return len(ids)
```

- [ ] **Step 4: Ruta DELETE dedicada**

En `app/routers/plan_movements.py`, **antes** del `@router.delete("/plans/{plan_id}/movements/{movement_id}", ...)`:
```python
@router.delete("/plans/{plan_id}/movements/tarjetazos")
def delete_tarjetazos(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"deleted": plan_movement_service.delete_tarjetazos(db, user, plan_id)}
```

- [ ] **Step 5: Correr (pasa) + suite completa**

Run: `pytest tests/test_plan_movements.py -q && pytest -q`
Expected: PASS (toda la suite).

- [ ] **Step 6: Commit**

```bash
git add app/services/plan_movement_service.py app/routers/plan_movements.py tests/test_plan_movements.py
git commit -m "feat: DELETE /plans/{id}/movements/tarjetazos (borrado masivo)"
```

---

## Notas de cierre

- Verificación manual rápida en dev (opcional): `uvicorn app.main:app --reload` y revisar `/docs` que aparezcan `POST` y `DELETE /plans/{id}/movements/tarjetazos`.
- El spec y el plan ya están commiteados por la tab de diseño; cada task commitea su propio código.
- Si `ALTER TYPE ... ADD VALUE` fallara por transacción (no debería en PG16), ejecutar la migración con autocommit (`with op.get_context().autocommit_block():`).

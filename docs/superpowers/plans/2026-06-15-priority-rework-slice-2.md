# Slice 2 — Campos de prioridad nuevos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar los campos de prioridad nuevos (`priority`, `payment_rule`, `monthly_paydown_amount`, `priority_open_debt`) a `obligations` y `credit_cards`, con validación en los endpoints de deuda y tarjeta. El motor del planning todavía no los usa (diferido al Slice 3).

**Architecture:** `payment_rule` es un enum Postgres compartido (`ninguno|minimo|total|mensual`, valores en español) usado por ambas tablas. Las columnas se agregan a `obligations` (deuda usa `priority`; deuda_abierta usa `monthly_paydown_amount` + `priority_open_debt`) y `credit_cards` (usa `priority`). La validación cruzada (qué regla permite cada tipo, priority sii regla≠ninguno, monthly sii mensual) vive en `obligation_common` y la usan los servicios de deuda y tarjeta. Los tests usan `create_all`, así que hay que recrear `margin_test` tras el cambio de esquema.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, pytest. `Decimal` para montos.

**Spec:** `docs/superpowers/specs/2026-06-14-priority-rework-design.md`

**Decisiones de implementación** (derivadas del spec + resoluciones del usuario):
- `payment_rule` NOT NULL, `server_default="ninguno"`. `priority`, `monthly_paydown_amount`, `priority_open_debt` nullable.
- **deuda**: regla ∈ {ninguno, minimo, total}; `priority` requerido sii regla≠ninguno; sin `monthly_paydown_amount`/`priority_open_debt`.
- **deuda_abierta**: regla ∈ {ninguno, mensual}; `monthly_paydown_amount` requerido y >0 sii regla=mensual; `priority_open_debt` opcional; sin `priority`.
- **tarjeta**: regla ∈ {ninguno, minimo, total}; `priority` requerido sii regla≠ninguno.
- Gastos (obligation_kind `gasto`) NO exponen estos campos: quedan en `ninguno`/NULL por el `server_default`.

**Contexto base:** `cd backend && source .venv/bin/activate`; tests `pytest -q`.

---

### Task 1: Enum compartido + columnas en los modelos

**Files:**
- Create: `app/models/enums.py`
- Modify: `app/models/obligation.py`
- Modify: `app/models/credit_card.py`

- [ ] **Step 1: Crear el enum compartido**

Crear `app/models/enums.py`:
```python
from sqlalchemy import Enum

# Enum Postgres compartido por obligations y credit_cards (un solo objeto = se crea una vez).
PAYMENT_RULE = Enum("ninguno", "minimo", "total", "mensual", name="payment_rule")
```

- [ ] **Step 2: Columnas en `Obligation`**

En `app/models/obligation.py`, agregar el import:
```python
from app.models.enums import PAYMENT_RULE
```
e insertar las columnas justo después de la línea `rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False)` y antes de `origin_obligation_id`:
```python
    payment_rule: Mapped[str] = mapped_column(PAYMENT_RULE, nullable=False, server_default="ninguno")
    priority: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    monthly_paydown_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    priority_open_debt: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
```

- [ ] **Step 3: Columnas en `CreditCard`**

En `app/models/credit_card.py`, agregar el import:
```python
from app.models.enums import PAYMENT_RULE
```
e insertar después de `rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False)` y antes de `reviewed_at`:
```python
    payment_rule: Mapped[str] = mapped_column(PAYMENT_RULE, nullable=False, server_default="ninguno")
    priority: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
```

- [ ] **Step 4: Recrear `margin_test` y verificar import + create_all**

```bash
dropdb margin_test && createdb margin_test
python -c "import app.main; from app.core.db import Base; from app.core.config import settings; from sqlalchemy import create_engine; Base.metadata.create_all(create_engine(settings.test_database_url)); print('CREATE_ALL OK')"
```
Expected: `CREATE_ALL OK` (el enum `payment_rule` se crea una sola vez).

- [ ] **Step 5: Commit**

```bash
git add app/models/enums.py app/models/obligation.py app/models/credit_card.py
git commit -m "feat: columnas priority/payment_rule/monthly_paydown_amount/priority_open_debt en los modelos"
```

---

### Task 2: Migración Alembic

**Files:**
- Create: `alembic/versions/<rev>_add_priority_fields.py`

- [ ] **Step 1: Generar la revisión**

Run: `alembic revision -m "add priority fields"`
Verificar que `down_revision = "2a2a7fdc153f"` (el head del Slice 1).

- [ ] **Step 2: Escribir `upgrade`/`downgrade`**

Reemplazar el cuerpo por (usa `postgresql.ENUM(create_type=False)` + creación explícita del tipo, idioma estándar de Alembic para enums):
```python
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def upgrade() -> None:
    payment_rule = postgresql.ENUM(
        "ninguno", "minimo", "total", "mensual", name="payment_rule", create_type=False
    )
    payment_rule.create(op.get_bind(), checkfirst=True)
    op.add_column("obligations", sa.Column("payment_rule", payment_rule, nullable=False, server_default="ninguno"))
    op.add_column("obligations", sa.Column("priority", sa.SmallInteger(), nullable=True))
    op.add_column("obligations", sa.Column("monthly_paydown_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("obligations", sa.Column("priority_open_debt", sa.SmallInteger(), nullable=True))
    op.add_column("credit_cards", sa.Column("payment_rule", payment_rule, nullable=False, server_default="ninguno"))
    op.add_column("credit_cards", sa.Column("priority", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("credit_cards", "priority")
    op.drop_column("credit_cards", "payment_rule")
    op.drop_column("obligations", "priority_open_debt")
    op.drop_column("obligations", "monthly_paydown_amount")
    op.drop_column("obligations", "priority")
    op.drop_column("obligations", "payment_rule")
    postgresql.ENUM(name="payment_rule").drop(op.get_bind(), checkfirst=True)
```
(Mantener los `revision`/`down_revision`/imports que generó Alembic; agregar el import de `postgresql` si falta.)

- [ ] **Step 3: Aplicar a la base de dev**

Run: `alembic upgrade head`
Expected: OK.

- [ ] **Step 4: Verificar cadena lineal**

Run: `alembic heads`
Expected: un solo head (la nueva revisión).

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: migración que agrega los campos de prioridad"
```

---

### Task 3: Error code + validadores

**Files:**
- Modify: `app/core/errors.py`
- Modify: `app/services/obligation_common.py`
- Test: `tests/test_obligation_common.py`

- [ ] **Step 1: Escribir los tests de los validadores**

En `tests/test_obligation_common.py`, agregar el import:
```python
from app.services.obligation_common import validate_payment_config
```
y los tests:
```python
def test_payment_config_deuda_ok():
    validate_payment_config("deuda", payment_rule="minimo", priority=1,
                            monthly_paydown_amount=None, priority_open_debt=None)  # no levanta


def test_payment_config_deuda_ninguno_con_priority_rechaza():
    with pytest.raises(AppError) as e:
        validate_payment_config("deuda", payment_rule="ninguno", priority=1,
                                monthly_paydown_amount=None, priority_open_debt=None)
    assert e.value.code == ErrorCode.payment_rule_invalid


def test_payment_config_deuda_regla_invalida():
    with pytest.raises(AppError) as e:
        validate_payment_config("deuda", payment_rule="mensual", priority=1,
                                monthly_paydown_amount=None, priority_open_debt=None)
    assert e.value.code == ErrorCode.payment_rule_invalid


def test_payment_config_abierta_mensual_ok():
    validate_payment_config("deuda_abierta", payment_rule="mensual", priority=None,
                            monthly_paydown_amount=Decimal("2000"), priority_open_debt=3)


def test_payment_config_abierta_mensual_sin_monto_rechaza():
    with pytest.raises(AppError) as e:
        validate_payment_config("deuda_abierta", payment_rule="mensual", priority=None,
                                monthly_paydown_amount=None, priority_open_debt=None)
    assert e.value.code == ErrorCode.amount_invalid


def test_payment_config_abierta_con_priority_rechaza():
    with pytest.raises(AppError) as e:
        validate_payment_config("deuda_abierta", payment_rule="ninguno", priority=2,
                                monthly_paydown_amount=None, priority_open_debt=None)
    assert e.value.code == ErrorCode.payment_rule_invalid
```

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_obligation_common.py -q -k payment_config`
Expected: FAIL (`validate_payment_config` no existe).

- [ ] **Step 3: Agregar el error code**

En `app/core/errors.py`, después de `expense_type_invalid = (...)` agregar:
```python
    payment_rule_invalid = (422, "La regla de pago no es válida para este tipo.")
```

- [ ] **Step 4: Agregar los validadores**

En `app/services/obligation_common.py`, agregar al final:
```python
PAYMENT_RULES_DEBT = ("ninguno", "minimo", "total")
PAYMENT_RULES_OPEN = ("ninguno", "mensual")


def _validate_priority_rule(payment_rule: str, priority, *, allowed) -> None:
    if payment_rule not in allowed:
        raise AppError(ErrorCode.payment_rule_invalid, field="payment_rule")
    # ninguno ⟺ sin priority
    if (payment_rule == "ninguno") != (priority is None):
        raise AppError(ErrorCode.payment_rule_invalid, field="priority")


def validate_payment_config(
    kind: str, *, payment_rule, priority, monthly_paydown_amount, priority_open_debt
) -> None:
    """Valida la combinación final de campos de prioridad según el tipo de deuda/tarjeta.
    kind: 'deuda' (también tarjeta) | 'deuda_abierta'."""
    if kind == "deuda_abierta":
        if payment_rule not in PAYMENT_RULES_OPEN:
            raise AppError(ErrorCode.payment_rule_invalid, field="payment_rule")
        if priority is not None:
            raise AppError(ErrorCode.payment_rule_invalid, field="priority")
        if payment_rule == "mensual":
            if monthly_paydown_amount is None or monthly_paydown_amount <= 0:
                raise AppError(ErrorCode.amount_invalid, field="monthly_paydown_amount")
        elif monthly_paydown_amount is not None:
            raise AppError(ErrorCode.payment_rule_invalid, field="monthly_paydown_amount")
    else:  # 'deuda' y tarjeta
        _validate_priority_rule(payment_rule, priority, allowed=PAYMENT_RULES_DEBT)
        if monthly_paydown_amount is not None or priority_open_debt is not None:
            raise AppError(ErrorCode.payment_rule_invalid, field="payment_rule")
```

- [ ] **Step 5: Correr (pasa)**

Run: `pytest tests/test_obligation_common.py -q -k payment_config`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/core/errors.py app/services/obligation_common.py tests/test_obligation_common.py
git commit -m "feat: validador validate_payment_config + error payment_rule_invalid"
```

---

### Task 4: Deuda — schema + servicio + tests

**Files:**
- Modify: `app/schemas/debt.py`
- Modify: `app/services/debt_service.py`
- Test: `tests/test_debts.py`

- [ ] **Step 1: Escribir los tests**

En `tests/test_debts.py`, agregar (usan los helpers/seeds existentes `catalog`, `_auth`, `_cronograma`; el catálogo tiene el tipo `deuda` id 10 y el `deuda_abierta` id 8):
```python
def test_post_deuda_con_priority_y_regla(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(payment_rule="minimo", priority=2), headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["payment_rule"] == "minimo"
    assert body["priority"] == 2


def test_post_deuda_regla_sin_priority_rechaza(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json=_cronograma(payment_rule="total"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "payment_rule_invalid"


def test_post_deuda_default_ninguno(client, db_session, catalog):
    headers = _auth(client)
    body = resp = client.post("/debts", json=_cronograma(), headers=headers).json()
    assert body["payment_rule"] == "ninguno"
    assert body["priority"] is None


def test_post_abierta_mensual(client, db_session, catalog):
    headers = _auth(client)
    resp = client.post("/debts", json={
        "obligation_type_id": 8, "description": "Le debo a mi viejo", "currency_id": 1,
        "amount": "100000.00", "payment_rule": "mensual",
        "monthly_paydown_amount": "2000.00", "priority_open_debt": 1,
    }, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["payment_rule"] == "mensual"
    assert body["monthly_paydown_amount"] == "2000.00"
    assert body["priority_open_debt"] == 1


def test_patch_deuda_payment_rule(client, db_session, catalog):
    headers = _auth(client)
    created = client.post("/debts", json=_cronograma(), headers=headers).json()
    resp = client.patch(f"/debts/{created['id']}",
                        json={"payment_rule": "minimo", "priority": 5}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["payment_rule"] == "minimo" and resp.json()["priority"] == 5
```

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_debts.py -q -k "priority or abierta_mensual or payment_rule or default_ninguno"`
Expected: FAIL (los campos no existen en el schema/servicio).

- [ ] **Step 3: Schema de deuda**

En `app/schemas/debt.py`, agregar a `DebtCreate` (tras `obligation_type_id`):
```python
    payment_rule: str | None = None
    priority: int | None = None
    monthly_paydown_amount: Decimal | None = None
    priority_open_debt: int | None = None
```
Agregar los mismos cuatro (todos `| None = None`) a `DebtUpdate`.
Agregar a `DebtOut` (tras `obligation_type_id`):
```python
    payment_rule: str
    priority: int | None
    monthly_paydown_amount: Decimal | None
    priority_open_debt: int | None
```
y en `from_model`, tras `obligation_type_id=o.obligation_type_id,`:
```python
            payment_rule=o.payment_rule,
            priority=o.priority,
            monthly_paydown_amount=o.monthly_paydown_amount,
            priority_open_debt=o.priority_open_debt,
```

- [ ] **Step 4: Servicio de deuda — create**

En `app/services/debt_service.py`, importar el validador:
```python
from app.services.obligation_common import (
    validate_amount,
    validate_description,
    validate_due_day,
    validate_payment_config,
)
```
En `create_debt`, después de `validate_amount(payload.amount)` (al inicio, antes del `if kind == "deuda":`):
```python
    rule = payload.payment_rule or "ninguno"
    validate_payment_config(
        kind, payment_rule=rule, priority=payload.priority,
        monthly_paydown_amount=payload.monthly_paydown_amount,
        priority_open_debt=payload.priority_open_debt,
    )
```
En la construcción `Obligation(...)` del branch `if kind == "deuda":`, agregar:
```python
            payment_rule=rule,
            priority=payload.priority,
            monthly_paydown_amount=None,
            priority_open_debt=None,
```
En la construcción `Obligation(...)` del branch `else:` (deuda_abierta), agregar:
```python
            payment_rule=rule,
            priority=None,
            monthly_paydown_amount=payload.monthly_paydown_amount,
            priority_open_debt=payload.priority_open_debt,
```

- [ ] **Step 5: Servicio de deuda — update**

En `update_debt`, después de aplicar/validar los campos existentes y antes de hacer commit, agregar la revalidación de la combinación final (usa los valores del payload si están en `fields`, si no los actuales de `obligation`). Insertar tras el bloque `if "amount" in fields: ...`:
```python
    rule = payload.payment_rule if "payment_rule" in fields else obligation.payment_rule
    pri = payload.priority if "priority" in fields else obligation.priority
    mpd = payload.monthly_paydown_amount if "monthly_paydown_amount" in fields else obligation.monthly_paydown_amount
    pod = payload.priority_open_debt if "priority_open_debt" in fields else obligation.priority_open_debt
    if any(f in fields for f in ("payment_rule", "priority", "monthly_paydown_amount", "priority_open_debt")):
        validate_payment_config(kind, payment_rule=rule, priority=pri,
                                monthly_paydown_amount=mpd, priority_open_debt=pod)
        obligation.payment_rule = rule
        obligation.priority = pri
        obligation.monthly_paydown_amount = mpd
        obligation.priority_open_debt = pod
```
(`kind` ya está disponible en `update_debt` — ver `kind = db.get(ObligationType, obligation.obligation_type_id).obligation_kind`.)

- [ ] **Step 6: Correr (pasa)**

Run: `pytest tests/test_debts.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/schemas/debt.py app/services/debt_service.py tests/test_debts.py
git commit -m "feat: deuda acepta priority/payment_rule/monthly_paydown_amount/priority_open_debt"
```

---

### Task 5: Tarjeta — schema + servicio + tests

**Files:**
- Modify: `app/schemas/credit_card.py`
- Modify: `app/services/credit_card_service.py`
- Test: `tests/test_credit_cards_mutations.py`

- [ ] **Step 1: Escribir los tests**

En `tests/test_credit_cards_mutations.py`, agregar (usar los helpers de ese archivo para crear/obtener una tarjeta; `<card_id>` es el id de una tarjeta del usuario):
```python
def test_patch_card_priority_y_regla(client, db_session, seed_cc_refs):
    card_id = _ready_card(client, db_session)          # helper existente que deja una tarjeta lista
    headers = _auth(client)
    resp = client.patch(f"/credit-cards/{card_id}",
                        json={"payment_rule": "minimo", "priority": 1}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["payment_rule"] == "minimo" and resp.json()["priority"] == 1


def test_patch_card_regla_sin_priority_rechaza(client, db_session, seed_cc_refs):
    card_id = _ready_card(client, db_session)
    headers = _auth(client)
    resp = client.patch(f"/credit-cards/{card_id}", json={"payment_rule": "total"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "payment_rule_invalid"
```
> Nota: usar el helper que ya exista en el archivo para obtener una tarjeta lista del usuario; si el nombre difiere de `_ready_card`/`_auth`, ajustar a los helpers reales del archivo.

- [ ] **Step 2: Correr (falla)**

Run: `pytest tests/test_credit_cards_mutations.py -q -k "priority or regla"`
Expected: FAIL.

- [ ] **Step 3: Schema de tarjeta**

En `app/schemas/credit_card.py`, agregar a `CreditCardOut` (tras `card_network_id`):
```python
    payment_rule: str
    priority: int | None
```
y en `from_model`, tras `card_network_id=c.card_network_id,`:
```python
            payment_rule=c.payment_rule,
            priority=c.priority,
```
Agregar a `CreditCardUpdate`:
```python
    payment_rule: str | None = None
    priority: int | None = None
```

- [ ] **Step 4: Servicio de tarjeta**

En `app/services/credit_card_service.py`, importar:
```python
from app.services.obligation_common import validate_payment_config
```
Sumar los dos campos al chequeo de `empty_patch` (para que un PATCH que solo trae `payment_rule`/`priority` no sea "vacío"):
```python
    if (
        payload.institution_id is None
        and payload.card_network_id is None
        and payload.closing_day is None
        and payload.due_day is None
        and payload.payment_rule is None
        and payload.priority is None
    ):
        raise AppError(ErrorCode.empty_patch)
```
Antes del commit/return de `update_credit_card`, agregar la revalidación + aplicación (tarjeta = reglas de 'deuda'):
```python
    if payload.payment_rule is not None or payload.priority is not None:
        rule = payload.payment_rule if payload.payment_rule is not None else card.payment_rule
        pri = payload.priority if payload.priority is not None else card.priority
        validate_payment_config("deuda", payment_rule=rule, priority=pri,
                                monthly_paydown_amount=None, priority_open_debt=None)
        card.payment_rule = rule
        card.priority = pri
```
> Nota: si el usuario quiere volver a `ninguno` y limpiar `priority`, mandar `payment_rule="ninguno"` (y el validador exige `priority` ausente/None — el front manda `priority: null`). El patrón "None = no tocar" del PATCH actual no permite *setear* priority a null explícito; alcanza para el Slice 2 (se afina en el Slice 3 si hace falta).

- [ ] **Step 5: Correr (pasa)**

Run: `pytest tests/test_credit_cards_mutations.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/schemas/credit_card.py app/services/credit_card_service.py tests/test_credit_cards_mutations.py
git commit -m "feat: tarjeta acepta priority/payment_rule"
```

---

### Task 6: Cierre

- [ ] **Step 1: Recrear `margin_test` y correr la suite completa**

```bash
dropdb margin_test && createdb margin_test
pytest -q
```
Expected: PASS (toda la suite).

- [ ] **Step 2: Verificar Alembic lineal en dev**

Run: `alembic heads`
Expected: un solo head (la revisión del Slice 2).

- [ ] **Step 3: Dejar listo para merge**

Reportar que el Slice 2 está completo en `feat/priority-rework`. El usuario pidió mergear después de este slice — usar `superpowers:finishing-a-development-branch` para verificar tests y ejecutar el merge a main (squash) + push, según su confirmación.

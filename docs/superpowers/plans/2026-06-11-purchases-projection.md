# Purchases: cuotas + proyección en CashFlowEngine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `purchases.total_installments` (NULL = 1) con validaciones, y que las compras con tarjeta posteriores al cierre del último resumen proyecten sus cuotas en las `cash_flow_entries` (primera cuota en M+1), re-materializando en cada escritura.

**Architecture:** Columna aditiva + validación cruzada en `purchase_service` (cuotas > 1 solo con tarjeta). En el engine, un helper `_purchase_sums` con el mismo shape que `_projection_sums` se suma al dict de la Responsabilidad 2 antes del densify. `purchase_service` dispara `materialize_credit_card` (flush antes, commit después) en create/update/delete con tarjeta. **`amount` es el valor de cada cuota, no el total.**

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + Postgres 16, pytest sobre `margin_test`.

**Spec:** `docs/superpowers/specs/2026-06-11-purchases-installments-projection-design.md`

**Directorio de trabajo:** `backend/`. Activar el entorno una vez por sesión: `source .venv/bin/activate`.

---

### Task 0: Rama

- [ ] **Step 0.1:**

```bash
git checkout main && git pull && git checkout -b feat/purchases-projection
```

---

### Task 1: Columna `total_installments` en el modelo

**Files:**
- Modify: `backend/app/models/purchase.py`
- Test: `backend/tests/test_purchases.py` (agregar)

- [ ] **Step 1.1: Test de round-trip (falla)**

Agregar a `backend/tests/test_purchases.py`:

```python
def test_purchase_installments_roundtrip(client, db_session, seed_uy_currency):
    user, _ = _register(db_session, client)
    db_session.add(Purchase(
        user_id=user.id, purchase_date=date(2026, 6, 10),
        amount=Decimal("500.00"), currency_id=1, total_installments=6,
    ))
    db_session.commit()
    row = db_session.execute(select(Purchase)).scalars().one()
    assert row.total_installments == 6
```

- [ ] **Step 1.2: Verificar que falla**

Run: `pytest tests/test_purchases.py::test_purchase_installments_roundtrip -q`
Expected: FAIL con `TypeError: 'total_installments' is an invalid keyword argument`

- [ ] **Step 1.3: Agregar la columna al modelo**

En `backend/app/models/purchase.py`, después de la línea de `currency_id`:

```python
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
```

- [ ] **Step 1.4: Verificar que pasa**

Run: `pytest tests/test_purchases.py::test_purchase_installments_roundtrip -q`
Expected: 1 passed

- [ ] **Step 1.5: Commit**

```bash
git add app/models/purchase.py tests/test_purchases.py
git commit -m "feat: columna total_installments en purchases (NULL = 1)"
```

---

### Task 2: Migración aditiva

**Files:**
- Create: `backend/alembic/versions/<rev>_add_total_installments_to_purchases.py`

- [ ] **Step 2.1: Autogenerar**

```bash
alembic revision --autogenerate -m "add total_installments to purchases"
```

- [ ] **Step 2.2: Revisar el archivo generado**

El `upgrade()` debe ser exactamente:

```python
    op.add_column('purchases', sa.Column('total_installments', sa.SmallInteger(), nullable=True))
```

y el `downgrade()`:

```python
    op.drop_column('purchases', 'total_installments')
```

Si el autogenerate detectó otra cosa (diff de otra tabla), borrar esas líneas: la migración es solo esta columna.

- [ ] **Step 2.3: Aplicar y verificar**

```bash
alembic upgrade head
psql -d margin -tA -c "select column_name from information_schema.columns where table_name='purchases' and column_name='total_installments';"
```

Expected: `total_installments`

- [ ] **Step 2.4: Commit**

```bash
git add alembic/versions/
git commit -m "feat: migración add total_installments a purchases"
```

---

### Task 3: Validaciones de cuotas + schemas

**Files:**
- Modify: `backend/app/schemas/purchase.py`
- Modify: `backend/app/services/purchase_service.py`
- Test: `backend/tests/test_purchases.py` (agregar)

- [ ] **Step 3.1: Tests de validación (fallan)**

Agregar a `backend/tests/test_purchases.py` (helpers `_register`, `_card`, `_body`, `_created` ya existen):

```python
def test_post_card_with_installments(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id), total_installments=6), headers=headers)
    assert r.status_code == 201
    assert r.json()["total_installments"] == 6


def test_post_cash_with_installments_invalid(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(total_installments=2), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "installments_invalid"


def test_post_cash_one_installment_ok(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(total_installments=1), headers=headers)
    assert r.status_code == 201
    assert r.json()["total_installments"] == 1


def test_post_zero_installments_invalid(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id), total_installments=0), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "installments_invalid"


def test_patch_to_cash_with_installments_rejected(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    created = _created(client, headers, credit_card_id=str(card.id), total_installments=3)
    r = client.patch(f"/purchases/{created['id']}", json={"credit_card_id": None}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "installments_invalid"


def test_patch_to_cash_clearing_installments_ok(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    created = _created(client, headers, credit_card_id=str(card.id), total_installments=3)
    body = {"credit_card_id": None, "total_installments": None}
    r = client.patch(f"/purchases/{created['id']}", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json()["credit_card_id"] is None
    assert r.json()["total_installments"] is None


def test_patch_installments_null_back_to_single(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    created = _created(client, headers, credit_card_id=str(card.id), total_installments=3)
    r = client.patch(f"/purchases/{created['id']}", json={"total_installments": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["total_installments"] is None
```

- [ ] **Step 3.2: Verificar que fallan**

Run: `pytest tests/test_purchases.py -q`
Expected: los 7 nuevos fallan (Pydantic ignora el campo desconocido → 201 sin `total_installments` en la
respuesta, o KeyError); el resto verde.

- [ ] **Step 3.3: Schemas**

En `backend/app/schemas/purchase.py`:

1. En `PurchaseCreate` y en `PurchaseUpdate`, después de `category_id`:

```python
    total_installments: int | None = None
```

2. En `PurchaseOut`, después de `category_id`:

```python
    total_installments: int | None
```

3. En `from_model`, después de `category_id=p.category_id,`:

```python
            total_installments=p.total_installments,
```

- [ ] **Step 3.4: Service**

En `backend/app/services/purchase_service.py`:

1. Sumar el campo a `_EDITABLE` (NO a `_NOT_NULLABLE`: null explícito = vuelve a contado):

```python
_EDITABLE = (
    "credit_card_id", "category_id", "description", "purchase_date",
    "amount", "currency_id", "total_installments",
)
```

2. Validador nuevo, debajo de `_validate_category`:

```python
def _validate_installments(total_installments: int | None, credit_card_id: uuid.UUID | None) -> None:
    if total_installments is None:
        return
    if total_installments < 1:
        raise AppError(ErrorCode.installments_invalid, field="total_installments")
    if total_installments > 1 and credit_card_id is None:
        raise AppError(ErrorCode.installments_invalid, field="total_installments")
```

3. En `create_purchase`, después de `_validate_category(...)`:

```python
    _validate_installments(payload.total_installments, payload.credit_card_id)
```

y en el constructor de `Purchase(...)`, después de `category_id=payload.category_id,`:

```python
        total_installments=payload.total_installments,
```

4. En `update_purchase`, después de `_validate_category(db, final("category_id"))`:

```python
    _validate_installments(final("total_installments"), final("credit_card_id"))
```

- [ ] **Step 3.5: Verificar que pasan**

Run: `pytest tests/test_purchases.py -q`
Expected: todos verdes

- [ ] **Step 3.6: Commit**

```bash
git add app/schemas/purchase.py app/services/purchase_service.py tests/test_purchases.py
git commit -m "feat: validaciones de cuotas en purchases (solo tarjeta, >= 1)"
```

---

### Task 4: Engine — `_purchase_sums` en la Responsabilidad 2

**Files:**
- Modify: `backend/app/services/cash_flow/credit_cards.py`
- Test: `backend/tests/test_cashflow_credit_cards.py` (agregar)

- [ ] **Step 4.1: Tests del engine (fallan)**

Agregar al final de `backend/tests/test_cashflow_credit_cards.py`. Contexto de las fixtures: `user_uy`
siembra UY + Peso(1) + Dólar(3) + institución 1 + red 1; `_make_statement` por defecto cierra el
**2026-05-13** (M = mayo → primera cuota proyectada en junio); `_by_key` indexa las entries por
`(issue_year, issue_month, currency_id)`. El densify rellena con 0, por eso los meses sin cuota se
asertan `== Decimal("0")`.

```python
def _add_purchase(db_session, user, card, *, amount="1000.00", purchase_date=date(2026, 5, 20),
                  total_installments=None, currency_id=1):
    from app.models.purchase import Purchase

    p = Purchase(
        user_id=user.id,
        credit_card_id=card.id,
        purchase_date=purchase_date,
        amount=Decimal(amount),
        currency_id=currency_id,
        total_installments=total_installments,
    )
    db_session.add(p)
    db_session.flush()
    return p


def test_purchase_post_closing_projects_m1(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card, total_usd=Decimal("0.00"))  # cierre 2026-05-13
    _add_purchase(db_session, user_uy, card, amount="1000.00", purchase_date=date(2026, 5, 20))
    materialize_credit_card(db_session, card.id, today=TODAY)
    keys = _by_key(db_session, card)
    assert keys[(2026, 6, 1)].amount == Decimal("1000.00")  # cuotas NULL = 1 cuota
    assert keys[(2026, 7, 1)].amount == Decimal("0")


def test_purchase_installments_project_consecutive_months(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_purchase(db_session, user_uy, card, amount="500.00",
                  purchase_date=date(2026, 5, 20), total_installments=3)
    materialize_credit_card(db_session, card.id, today=TODAY)
    keys = _by_key(db_session, card)
    for month in (6, 7, 8):
        assert keys[(2026, month, 1)].amount == Decimal("500.00")
    assert keys[(2026, 9, 1)].amount == Decimal("0")


def test_purchase_on_closing_date_excluded(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_purchase(db_session, user_uy, card, purchase_date=date(2026, 5, 13))  # == cierre: capturada
    materialize_credit_card(db_session, card.id, today=TODAY)
    assert _by_key(db_session, card)[(2026, 6, 1)].amount == Decimal("0")


def test_purchase_other_card_excluded(db_session, user_uy):
    from app.models.institution import Institution

    db_session.add(Institution(id=2, country_code="UY", name="Itaú", visible=True))
    db_session.flush()
    card = _make_card(db_session, user_uy)
    other = _make_card(db_session, user_uy, institution_id=2)
    _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_purchase(db_session, user_uy, other, purchase_date=date(2026, 5, 20))
    materialize_credit_card(db_session, card.id, today=TODAY)
    assert _by_key(db_session, card)[(2026, 6, 1)].amount == Decimal("0")


def test_purchase_installments_capped_at_horizon(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_purchase(db_session, user_uy, card, amount="100.00",
                  purchase_date=date(2026, 5, 20), total_installments=600)
    materialize_credit_card(db_session, card.id, today=TODAY)
    keys = _by_key(db_session, card)
    assert keys[(2027, 12, 1)].amount == Decimal("100.00")  # HORIZON = 2027-12-31
    assert (2028, 1, 1) not in keys


def test_purchase_usd_goes_to_usd_series(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _make_statement(db_session, card, total_usd=Decimal("0.00"))
    _add_purchase(db_session, user_uy, card, amount="50.00",
                  purchase_date=date(2026, 5, 20), currency_id=3)
    materialize_credit_card(db_session, card.id, today=TODAY)
    keys = _by_key(db_session, card)
    assert keys[(2026, 6, 3)].amount == Decimal("50.00")
    assert keys[(2026, 6, 1)].amount == Decimal("0")


def test_purchase_without_statement_not_projected(db_session, user_uy):
    card = _make_card(db_session, user_uy)
    _add_purchase(db_session, user_uy, card, purchase_date=date(2026, 5, 20))
    materialize_credit_card(db_session, card.id, today=TODAY)
    assert _orm_entries(db_session, card) == []  # gate actual: sin resumen no hay proyección
```

- [ ] **Step 4.2: Verificar que fallan**

Run: `pytest tests/test_cashflow_credit_cards.py -q`
Expected: fallan los 4 que esperan montos proyectados (`projects_m1`, `consecutive_months`,
`capped_at_horizon`, `usd_series`) porque el engine ignora `purchases` y todo da `0`. Los 3 de exclusión
(`on_closing_date_excluded`, `other_card_excluded`, `without_statement_not_projected`) pasan ya — quedan
como guardas de regresión. El resto del archivo verde.

- [ ] **Step 4.3: Implementar `_purchase_sums`**

En `backend/app/services/cash_flow/credit_cards.py`:

1. Agregar el import (junto a los demás `app.models`):

```python
from app.models.purchase import Purchase
```

2. Helper nuevo, debajo de `_projection_sums`:

```python
def _purchase_sums(
    db: Session, card: CreditCard, statement: CreditCardStatement, horizon: date
) -> dict[tuple[int, int, int], Decimal]:
    """{(year, month, currency_id): monto} de las cuotas de compras de la tarjeta posteriores al
    cierre del último resumen; primera cuota en M+1 (M = mes del closing_date). amount es por cuota."""
    purchases = db.execute(
        select(Purchase).where(
            Purchase.credit_card_id == card.id,
            Purchase.purchase_date > statement.closing_date,
        )
    ).scalars()

    base_y, base_m = statement.closing_date.year, statement.closing_date.month
    horizon_key = (horizon.year, horizon.month)
    sums: dict[tuple[int, int, int], Decimal] = {}

    for purchase in purchases:
        for k in range(1, (purchase.total_installments or 1) + 1):
            y, m = _add_months(base_y, base_m, k)
            if (y, m) > horizon_key:
                break
            key = (y, m, purchase.currency_id)
            sums[key] = sums.get(key, Decimal("0")) + purchase.amount

    return sums
```

3. En `materialize_credit_card`, Responsabilidad 2, sumar las compras antes del densify. El bloque

```python
        sums = _projection_sums(db, statement, horizon)
        _densify_projection(sums, statement, horizon, (local_id, usd_id))
```

queda:

```python
        sums = _projection_sums(db, statement, horizon)
        for key, amount in _purchase_sums(db, card, statement, horizon).items():
            sums[key] = sums.get(key, Decimal("0")) + amount
        _densify_projection(sums, statement, horizon, (local_id, usd_id))
```

- [ ] **Step 4.4: Verificar que pasan**

Run: `pytest tests/test_cashflow_credit_cards.py -q`
Expected: todos verdes

- [ ] **Step 4.5: Commit**

```bash
git add app/services/cash_flow/credit_cards.py tests/test_cashflow_credit_cards.py
git commit -m "feat: compras post-cierre proyectan cuotas en el CashFlowEngine"
```

---

### Task 5: Disparadores — re-materializar al escribir compras

**Files:**
- Modify: `backend/app/services/purchase_service.py`
- Modify: `backend/tests/test_purchases.py` (helper `_card` + tests)

- [ ] **Step 5.1: Tests de integración (fallan)**

En `backend/tests/test_purchases.py`:

1. Extender la firma del helper `_card` existente para permitir otra institución (la unicidad de tarjeta
es por usuario+institución+red):

```python
def _card(db_session, user, deleted_at=None, institution_id=1):
```

y dentro del constructor usar `institution_id=institution_id` en lugar de `institution_id=1`.

2. Agregar helpers y tests:

```python
def _statement(db_session, card):
    from app.models.credit_card_statement import CreditCardStatement

    st = CreditCardStatement(
        credit_card_id=card.id, issue_year=2026, issue_month=5,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25),
        total_local=Decimal("1000.00"), total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("100.00"), minimum_payment_usd=Decimal("0.00"),
    )
    db_session.add(st)
    db_session.commit()
    return st


def _entry_amounts(db_session, card):
    from app.models.cash_flow_entry import CashFlowEntry

    rows = db_session.execute(
        select(CashFlowEntry).where(
            CashFlowEntry.source_type == "tarjeta_credito",
            CashFlowEntry.source_id == card.id,
        )
    ).scalars()
    return {(e.issue_year, e.issue_month, e.currency_id): e.amount for e in rows}


def test_post_card_purchase_materializes(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    body = _body(credit_card_id=str(card.id), purchase_date="2026-06-10", amount="800.00")
    assert client.post("/purchases", json=body, headers=headers).status_code == 201
    assert _entry_amounts(db_session, card)[(2026, 6, 1)] == Decimal("800.00")


def test_post_cash_purchase_does_not_materialize(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    assert client.post("/purchases", json=_body(), headers=headers).status_code == 201
    assert _entry_amounts(db_session, card) == {}  # efectivo no dispara el engine


def test_patch_amount_rematerializes(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    created = _created(client, headers, credit_card_id=str(card.id), purchase_date="2026-06-10", amount="800.00")
    r = client.patch(f"/purchases/{created['id']}", json={"amount": "900.00"}, headers=headers)
    assert r.status_code == 200
    assert _entry_amounts(db_session, card)[(2026, 6, 1)] == Decimal("900.00")


def test_patch_to_cash_removes_from_projection(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    created = _created(client, headers, credit_card_id=str(card.id), purchase_date="2026-06-10", amount="800.00")
    r = client.patch(f"/purchases/{created['id']}", json={"credit_card_id": None}, headers=headers)
    assert r.status_code == 200
    assert _entry_amounts(db_session, card)[(2026, 6, 1)] == Decimal("0")


def test_delete_rematerializes(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    _statement(db_session, card)
    created = _created(client, headers, credit_card_id=str(card.id), purchase_date="2026-06-10", amount="800.00")
    assert client.delete(f"/purchases/{created['id']}", headers=headers).status_code == 204
    assert _entry_amounts(db_session, card)[(2026, 6, 1)] == Decimal("0")


def test_patch_change_card_rematerializes_both(client, db_session, seed_cc_refs):
    from app.models.institution import Institution

    user, headers = _register(db_session, client)
    db_session.add(Institution(id=2, country_code="UY", name="Itaú", visible=True))
    db_session.commit()
    card_a = _card(db_session, user)
    card_b = _card(db_session, user, institution_id=2)
    _statement(db_session, card_a)
    _statement(db_session, card_b)
    created = _created(client, headers, credit_card_id=str(card_a.id), purchase_date="2026-06-10", amount="800.00")
    r = client.patch(f"/purchases/{created['id']}", json={"credit_card_id": str(card_b.id)}, headers=headers)
    assert r.status_code == 200
    assert _entry_amounts(db_session, card_a)[(2026, 6, 1)] == Decimal("0")
    assert _entry_amounts(db_session, card_b)[(2026, 6, 1)] == Decimal("800.00")
```

Nota: el `0` en las aserciones existe porque el densify rellena cada mes proyectado con `Decimal("0")`
cuando la tarjeta tiene resumen.

- [ ] **Step 5.2: Verificar que fallan**

Run: `pytest tests/test_purchases.py -q`
Expected: fallan 5 con `KeyError` (no hay entries porque el service todavía no materializa):
`post_card_purchase_materializes`, `patch_amount`, `patch_to_cash`, `delete`, `change_card`.
`test_post_cash_purchase_does_not_materialize` pasa ya (documenta que efectivo no dispara). El resto verde.

- [ ] **Step 5.3: Implementar los disparadores**

En `backend/app/services/purchase_service.py`:

1. Import (debajo de `from app.services.scoping import require_holdable_currency`):

```python
from app.services.cash_flow.credit_cards import materialize_credit_card
```

2. En `create_purchase`, el cierre

```python
    db.add(p)
    db.commit()
    db.refresh(p)
    return p
```

queda (flush ANTES de materializar para que el engine vea la compra nueva):

```python
    db.add(p)
    db.flush()
    if p.credit_card_id is not None:
        materialize_credit_card(db, p.credit_card_id)
    db.commit()
    db.refresh(p)
    return p
```

3. En `update_purchase`: capturar la tarjeta original ANTES de aplicar el patch. La línea
`p = _require_purchase(db, user, purchase_id)` queda seguida de:

```python
    old_card_id = p.credit_card_id
```

y el cierre

```python
    db.flush()
    db.commit()
    db.refresh(p)
    return p
```

queda:

```python
    db.flush()
    for card_id in {old_card_id, p.credit_card_id} - {None}:
        materialize_credit_card(db, card_id)
    db.commit()
    db.refresh(p)
    return p
```

4. En `delete_purchase`:

```python
def delete_purchase(db: Session, user: User, purchase_id: uuid.UUID) -> None:
    p = _require_purchase(db, user, purchase_id)
    card_id = p.credit_card_id
    db.delete(p)
    db.flush()
    if card_id is not None:
        materialize_credit_card(db, card_id)
    db.commit()
```

- [ ] **Step 5.4: Verificar que pasan**

Run: `pytest tests/test_purchases.py -q`
Expected: todos verdes

- [ ] **Step 5.5: Commit**

```bash
git add app/services/purchase_service.py tests/test_purchases.py
git commit -m "feat: escribir una compra con tarjeta re-materializa sus cash_flow_entries"
```

---

### Task 6: Verificación final

- [ ] **Step 6.1: Suite completa**

Run: `pytest -q`
Expected: TODA la suite verde (sin warnings nuevos).

- [ ] **Step 6.2: Migración en dev**

```bash
psql -d margin -c "\d purchases"
```

Expected: columna `total_installments smallint` nullable.

- [ ] **Step 6.3: Cierre**

Usar la skill superpowers:finishing-a-development-branch. Convención del repo: **squash-merge** a `main`
(un commit por feature).

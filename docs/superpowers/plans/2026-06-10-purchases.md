# Purchases (compras con categoría) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registro de compras del usuario (tarjeta o efectivo) con categoría de gasto: catálogo `purchase_categories` sembrado + tabla `purchases` + CRUD `/purchases` + catálogo en `GET /bootstrap`.

**Architecture:** Dos tablas nuevas independientes del circuito de statements. Patrón estándar del repo: modelo SQLAlchemy → migración Alembic con seed → schemas Pydantic → service (validaciones todo-antes-de-escribir, `AppError`) → router finito. PATCH parcial con `model_fields_set` (patrón financings).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + Postgres 16, pytest sobre `margin_test`.

**Spec:** `docs/superpowers/specs/2026-06-10-purchases-design.md`

**Directorio de trabajo:** `backend/`. Activar el entorno una vez por sesión: `source .venv/bin/activate`.

---

### Task 0: Rama

- [ ] **Step 0.1:** Crear la rama de trabajo desde `main` actualizado:

```bash
git checkout main && git pull && git checkout -b feat/purchases
```

---

### Task 1: Modelos `PurchaseCategory` y `Purchase`

**Files:**
- Create: `backend/app/models/purchase_category.py`
- Create: `backend/app/models/purchase.py`
- Modify: `backend/app/models/__init__.py` (agregar 2 imports al final)
- Test: `backend/tests/test_purchases.py` (nuevo)

- [ ] **Step 1.1: Escribir los tests de round-trip (fallan)**

Crear `backend/tests/test_purchases.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.auth_identity import AuthIdentity
from app.models.purchase import Purchase
from app.models.purchase_category import PurchaseCategory
from app.models.user import User


def _register(db_session, client, email="u@b.com"):
    """Registra un usuario vía API y devuelve (user, headers con token).

    Se resuelve el usuario por su identidad (email), no por created_at: en tests con
    seed_cc_refs conviven dos usuarios creados en la misma transacción y now() empata.
    """
    token = client.post("/auth/register", json={"email": email, "password": "12345678"}).json()["token"]
    identity = db_session.execute(
        select(AuthIdentity).where(AuthIdentity.identifier == email)
    ).scalars().one()
    user = db_session.get(User, identity.user_id)
    return user, {"Authorization": f"Bearer {token}"}


def _seed_categories(db_session):
    db_session.add_all([
        PurchaseCategory(id=1, code="comida", name="Comida", emoji="🍔"),
        PurchaseCategory(id=12, code="otros", name="Otros", emoji="🧩"),
    ])
    db_session.commit()


def test_purchase_category_roundtrip(db_session):
    db_session.add(PurchaseCategory(id=1, code="comida", name="Comida", emoji="🍔"))
    db_session.commit()
    row = db_session.get(PurchaseCategory, 1)
    assert row.code == "comida"
    assert row.emoji == "🍔"


def test_purchase_roundtrip_full(client, db_session, seed_uy_currency):
    _seed_categories(db_session)
    user, _ = _register(db_session, client)
    db_session.add(Purchase(
        user_id=user.id, category_id=1, description="Almuerzo",
        purchase_date=date(2026, 6, 10), amount=Decimal("450.00"), currency_id=1,
    ))
    db_session.commit()
    row = db_session.execute(select(Purchase)).scalars().one()
    assert row.amount == Decimal("450.00")
    assert row.credit_card_id is None
    assert row.category_id == 1


def test_purchase_roundtrip_nullables(client, db_session, seed_uy_currency):
    user, _ = _register(db_session, client)
    db_session.add(Purchase(
        user_id=user.id, purchase_date=date(2026, 6, 10),
        amount=Decimal("100.00"), currency_id=1,
    ))
    db_session.commit()
    row = db_session.execute(select(Purchase)).scalars().one()
    assert row.category_id is None
    assert row.description is None
```

- [ ] **Step 1.2: Verificar que fallan**

Run: `pytest tests/test_purchases.py -q`
Expected: FAIL/ERROR con `ModuleNotFoundError: No module named 'app.models.purchase'`

- [ ] **Step 1.3: Crear los modelos**

Crear `backend/app/models/purchase_category.py`:

```python
from sqlalchemy import SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PurchaseCategory(Base):
    __tablename__ = "purchase_categories"
    __table_args__ = (UniqueConstraint("code", name="uq_purchase_categories_code"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)
```

Crear `backend/app/models/purchase.py`:

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Purchase(Base):
    __tablename__ = "purchases"
    __table_args__ = (Index("ix_purchases_user_id_purchase_date", "user_id", "purchase_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    credit_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_cards.id"), nullable=True
    )
    category_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("purchase_categories.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

Agregar al final de `backend/app/models/__init__.py`:

```python
from app.models.purchase_category import PurchaseCategory  # noqa: F401
from app.models.purchase import Purchase  # noqa: F401
```

- [ ] **Step 1.4: Verificar que pasan**

Run: `pytest tests/test_purchases.py -q`
Expected: 3 passed

- [ ] **Step 1.5: Commit**

```bash
git add app/models/purchase_category.py app/models/purchase.py app/models/__init__.py tests/test_purchases.py
git commit -m "feat: modelos PurchaseCategory y Purchase"
```

---

### Task 2: Migración con seed del catálogo

**Files:**
- Create: `backend/alembic/versions/<rev>_create_purchases.py` (autogenerada + seed a mano)

- [ ] **Step 2.1: Autogenerar la migración**

```bash
alembic revision --autogenerate -m "create purchases and purchase_categories"
```

- [ ] **Step 2.2: Revisar y completar la migración**

Abrir el archivo generado en `alembic/versions/`. Verificar que el `upgrade()` crea `purchase_categories`
ANTES que `purchases` (FK), con `sa.UniqueConstraint('code', name='uq_purchase_categories_code')` y el índice
`ix_purchases_user_id_purchase_date`. Agregar el seed AL FINAL de `upgrade()` (mismo patrón que
`342b00cc89fc_create_credit_card_item_types.py`):

```python
    op.bulk_insert(
        sa.table(
            "purchase_categories",
            sa.column("id", sa.SmallInteger),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("emoji", sa.String),
        ),
        [
            {"id": 1, "code": "comida", "name": "Comida", "emoji": "🍔"},
            {"id": 2, "code": "supermercado", "name": "Supermercado", "emoji": "🛒"},
            {"id": 3, "code": "transporte", "name": "Transporte", "emoji": "🚌"},
            {"id": 4, "code": "hogar", "name": "Hogar", "emoji": "🏠"},
            {"id": 5, "code": "salud", "name": "Salud", "emoji": "💊"},
            {"id": 6, "code": "ocio", "name": "Ocio", "emoji": "🎮"},
            {"id": 7, "code": "ropa", "name": "Ropa", "emoji": "👕"},
            {"id": 8, "code": "servicios", "name": "Servicios", "emoji": "💡"},
            {"id": 9, "code": "suscripciones", "name": "Suscripciones", "emoji": "📺"},
            {"id": 10, "code": "cafe", "name": "Café", "emoji": "☕"},
            {"id": 11, "code": "mascotas", "name": "Mascotas", "emoji": "🐶"},
            {"id": 12, "code": "otros", "name": "Otros", "emoji": "🧩"},
        ],
    )
```

En `downgrade()` el autogenerate ya dropea ambas tablas (el seed cae con la tabla); verificar orden:
`purchases` antes que `purchase_categories`.

- [ ] **Step 2.3: Aplicar y verificar**

```bash
alembic upgrade head
psql -d margin -tA -c "select count(*) from purchase_categories;"
```

Expected: `12`

- [ ] **Step 2.4: Commit**

```bash
git add alembic/versions/
git commit -m "feat: migración purchases + seed de purchase_categories"
```

---

### Task 3: `POST /purchases`

**Files:**
- Modify: `backend/app/core/errors.py` (2 códigos nuevos, después de `duplicate_currency`)
- Create: `backend/app/schemas/purchase.py`
- Create: `backend/app/services/purchase_service.py`
- Create: `backend/app/routers/purchases.py`
- Modify: `backend/app/main.py` (import + include_router)
- Test: `backend/tests/test_purchases.py` (agregar)

- [ ] **Step 3.1: Escribir los tests del POST (fallan)**

Agregar a `backend/tests/test_purchases.py` (los helpers `_register` y `_seed_categories` ya están del Task 1):

```python
from app.models.credit_card import CreditCard
from app.models.currency import Currency


def _card(db_session, user, deleted_at=None):
    """Tarjeta del usuario. Requiere fixture seed_cc_refs (siembra institución 1 y red 1)."""
    card = CreditCard(
        user_id=user.id, institution_id=1, card_network_id=1, current_limit=Decimal("100000.00"),
        closing_day=13, due_day=25, financing_rate_local=Decimal("10.00"),
        overdue_rate_local=Decimal("12.00"), financing_rate_usd=Decimal("5.00"),
        overdue_rate_usd=Decimal("6.00"), rates_add_vat=False,
        review_findings="[]", is_ready=True, deleted_at=deleted_at,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def _body(**overrides):
    body = {"purchase_date": "2026-06-10", "amount": "450.00", "currency_id": 1}
    body.update(overrides)
    return body


def test_post_requires_auth(client, db_session, seed_uy_currency):
    assert client.post("/purchases", json=_body()).status_code == 401


def test_post_cash_purchase(client, db_session, seed_uy_currency):
    _seed_categories(db_session)
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(category_id=1, description="Almuerzo"), headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["credit_card_id"] is None
    assert body["category_id"] == 1
    assert body["amount"] == "450.00"
    assert body["purchase_date"] == "2026-06-10"


def test_post_card_purchase(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id)), headers=headers)
    assert r.status_code == 201
    assert r.json()["credit_card_id"] == str(card.id)


def test_post_foreign_card_invalid(client, db_session, seed_cc_refs):
    other = seed_cc_refs  # usuario sembrado por la fixture, dueño de la tarjeta
    card = _card(db_session, other)
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id)), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "credit_card_invalid"


def test_post_deleted_card_invalid(client, db_session, seed_cc_refs):
    from datetime import datetime, timezone

    user, headers = _register(db_session, client)
    card = _card(db_session, user, deleted_at=datetime.now(timezone.utc))
    r = client.post("/purchases", json=_body(credit_card_id=str(card.id)), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "credit_card_invalid"


def test_post_unknown_category(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(category_id=999), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "purchase_category_invalid"


def test_post_without_category(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(), headers=headers)
    assert r.status_code == 201
    assert r.json()["category_id"] is None


def test_post_currency_not_holdable(client, db_session, seed_uy_currency):
    db_session.add(Currency(id=4, country_code="UY", name="UI", is_legal_tender=False, allowed_in_credit_card=False))
    db_session.commit()
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(currency_id=4), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "currency_not_available"


def test_post_amount_zero(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(amount="0.00"), headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "amount_invalid"


def test_post_blank_description_stored_null(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    r = client.post("/purchases", json=_body(description="   "), headers=headers)
    assert r.status_code == 201
    assert r.json()["description"] is None
```

- [ ] **Step 3.2: Verificar que fallan**

Run: `pytest tests/test_purchases.py -q`
Expected: los tests nuevos fallan con 404 (la ruta no existe); los 3 del Task 1 siguen verdes.

- [ ] **Step 3.3: Agregar los códigos de error**

En `backend/app/core/errors.py`, después de la línea `duplicate_currency = (422, "No repitas la misma moneda.")`:

```python
    credit_card_invalid = (422, "Tarjeta no válida.")
    purchase_category_invalid = (422, "Categoría no válida.")
```

- [ ] **Step 3.4: Crear los schemas**

Crear `backend/app/schemas/purchase.py`:

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.purchase import Purchase


class PurchaseCreate(BaseModel):
    credit_card_id: uuid.UUID | None = None
    category_id: int | None = None
    description: str | None = None
    purchase_date: date
    amount: Decimal
    currency_id: int


class PurchaseUpdate(BaseModel):
    credit_card_id: uuid.UUID | None = None
    category_id: int | None = None
    description: str | None = None
    purchase_date: date | None = None
    amount: Decimal | None = None
    currency_id: int | None = None


class PurchaseOut(BaseModel):
    id: uuid.UUID
    credit_card_id: uuid.UUID | None
    category_id: int | None
    description: str | None
    purchase_date: date
    amount: Decimal
    currency_id: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, p: Purchase) -> "PurchaseOut":
        return cls(
            id=p.id,
            credit_card_id=p.credit_card_id,
            category_id=p.category_id,
            description=p.description,
            purchase_date=p.purchase_date,
            amount=p.amount,
            currency_id=p.currency_id,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
```

- [ ] **Step 3.5: Crear el service (solo create por ahora)**

Crear `backend/app/services/purchase_service.py`:

```python
import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.credit_card import CreditCard
from app.models.purchase import Purchase
from app.models.purchase_category import PurchaseCategory
from app.models.user import User
from app.schemas.purchase import PurchaseCreate
from app.services.scoping import require_holdable_currency


def _clean_description(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _validate_amount(amount) -> None:
    if amount <= 0:
        raise AppError(ErrorCode.amount_invalid, field="amount")


def _validate_credit_card(db: Session, user: User, credit_card_id: uuid.UUID | None) -> None:
    if credit_card_id is None:
        return
    card = db.get(CreditCard, credit_card_id)
    if card is None or card.user_id != user.id or card.deleted_at is not None:
        raise AppError(ErrorCode.credit_card_invalid, field="credit_card_id")


def _validate_category(db: Session, category_id: int | None) -> None:
    if category_id is None:
        return
    if db.get(PurchaseCategory, category_id) is None:
        raise AppError(ErrorCode.purchase_category_invalid, field="category_id")


def create_purchase(db: Session, user: User, payload: PurchaseCreate) -> Purchase:
    require_holdable_currency(db, user, payload.currency_id)
    _validate_amount(payload.amount)
    _validate_credit_card(db, user, payload.credit_card_id)
    _validate_category(db, payload.category_id)
    p = Purchase(
        user_id=user.id,
        credit_card_id=payload.credit_card_id,
        category_id=payload.category_id,
        description=_clean_description(payload.description),
        purchase_date=payload.purchase_date,
        amount=payload.amount,
        currency_id=payload.currency_id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p
```

- [ ] **Step 3.6: Crear el router y registrarlo**

Crear `backend/app/routers/purchases.py`:

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.purchase import PurchaseCreate, PurchaseOut
from app.services import purchase_service

router = APIRouter(tags=["purchases"])


@router.post("/purchases", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def create_purchase(
    payload: PurchaseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOut:
    return PurchaseOut.from_model(purchase_service.create_purchase(db, user, payload))
```

En `backend/app/main.py`, el import queda:

```python
from app.routers import (
    auth, bootstrap, cash_balances, cash_flow_entries, cash_flow_payments, countries,
    credit_card_statements, credit_cards, debts, expenses, financings, health, incomes, obligations,
    plan_movements, plans, purchases,
)
```

y al final de los include:

```python
app.include_router(purchases.router)
```

- [ ] **Step 3.7: Verificar que pasan**

Run: `pytest tests/test_purchases.py -q`
Expected: todos verdes (3 del Task 1 + 10 del POST)

- [ ] **Step 3.8: Commit**

```bash
git add app/core/errors.py app/schemas/purchase.py app/services/purchase_service.py app/routers/purchases.py app/main.py tests/test_purchases.py
git commit -m "feat: POST /purchases con validaciones"
```

---

### Task 4: `GET /purchases`

**Files:**
- Modify: `backend/app/services/purchase_service.py`
- Modify: `backend/app/routers/purchases.py`
- Test: `backend/tests/test_purchases.py` (agregar)

- [ ] **Step 4.1: Escribir los tests (fallan)**

Agregar a `backend/tests/test_purchases.py`:

```python
def test_get_requires_auth(client, db_session, seed_uy_currency):
    assert client.get("/purchases").status_code == 401


def test_get_only_own_ordered_desc(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    _, other_headers = _register(db_session, client, email="otro@b.com")
    client.post("/purchases", json=_body(purchase_date="2026-06-01", description="vieja"), headers=headers)
    client.post("/purchases", json=_body(purchase_date="2026-06-10", description="nueva"), headers=headers)
    client.post("/purchases", json=_body(description="ajena"), headers=other_headers)
    body = client.get("/purchases", headers=headers).json()
    assert [p["description"] for p in body["purchases"]] == ["nueva", "vieja"]
```

- [ ] **Step 4.2: Verificar que fallan**

Run: `pytest tests/test_purchases.py -q`
Expected: los 2 nuevos fallan (405/404 en GET); el resto verde.

- [ ] **Step 4.3: Implementar**

En `backend/app/services/purchase_service.py`, agregar `select` al import de sqlalchemy
(`from sqlalchemy import select` arriba de `from sqlalchemy.orm import Session`) y al final:

```python
def list_purchases(db: Session, user: User) -> list[Purchase]:
    return list(
        db.execute(
            select(Purchase)
            .where(Purchase.user_id == user.id)
            .order_by(Purchase.purchase_date.desc(), Purchase.created_at.desc())
        ).scalars()
    )
```

En `backend/app/routers/purchases.py`, agregar:

```python
@router.get("/purchases")
def list_purchases(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"purchases": [PurchaseOut.from_model(p) for p in purchase_service.list_purchases(db, user)]}
```

- [ ] **Step 4.4: Verificar que pasan**

Run: `pytest tests/test_purchases.py -q`
Expected: todos verdes

- [ ] **Step 4.5: Commit**

```bash
git add app/services/purchase_service.py app/routers/purchases.py tests/test_purchases.py
git commit -m "feat: GET /purchases (listado del usuario, orden desc)"
```

---

### Task 5: `PATCH /purchases/{purchase_id}`

**Files:**
- Modify: `backend/app/services/purchase_service.py`
- Modify: `backend/app/routers/purchases.py`
- Test: `backend/tests/test_purchases.py` (agregar)

- [ ] **Step 5.1: Escribir los tests (fallan)**

Agregar a `backend/tests/test_purchases.py`:

```python
def _created(client, headers, **overrides):
    return client.post("/purchases", json=_body(**overrides), headers=headers).json()


def test_patch_category(client, db_session, seed_uy_currency):
    _seed_categories(db_session)
    _, headers = _register(db_session, client)
    created = _created(client, headers)
    r = client.patch(f"/purchases/{created['id']}", json={"category_id": 12}, headers=headers)
    assert r.status_code == 200
    assert r.json()["category_id"] == 12


def test_patch_card_to_cash(client, db_session, seed_cc_refs):
    user, headers = _register(db_session, client)
    card = _card(db_session, user)
    created = _created(client, headers, credit_card_id=str(card.id))
    r = client.patch(f"/purchases/{created['id']}", json={"credit_card_id": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["credit_card_id"] is None


def test_patch_empty(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    created = _created(client, headers)
    r = client.patch(f"/purchases/{created['id']}", json={}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "empty_patch"


def test_patch_purchase_date_null(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    created = _created(client, headers)
    r = client.patch(f"/purchases/{created['id']}", json={"purchase_date": None}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "field_not_nullable"


def test_patch_foreign_404(client, db_session, seed_uy_currency):
    _seed_categories(db_session)
    _, headers = _register(db_session, client)
    _, other_headers = _register(db_session, client, email="otro@b.com")
    created = _created(client, headers)
    r = client.patch(f"/purchases/{created['id']}", json={"category_id": 1}, headers=other_headers)
    assert r.status_code == 404
```

- [ ] **Step 5.2: Verificar que fallan**

Run: `pytest tests/test_purchases.py -q`
Expected: los 5 nuevos fallan (405 Method Not Allowed); el resto verde.

- [ ] **Step 5.3: Implementar**

En `backend/app/services/purchase_service.py`: agregar `PurchaseUpdate` al import de schemas
(`from app.schemas.purchase import PurchaseCreate, PurchaseUpdate`), las constantes debajo de los imports:

```python
_EDITABLE = ("credit_card_id", "category_id", "description", "purchase_date", "amount", "currency_id")
_NOT_NULLABLE = ("purchase_date", "amount", "currency_id")
```

y al final del archivo:

```python
def _require_purchase(db: Session, user: User, purchase_id: uuid.UUID) -> Purchase:
    p = db.get(Purchase, purchase_id)
    if p is None or p.user_id != user.id:
        raise AppError(ErrorCode.not_found)
    return p


def update_purchase(db: Session, user: User, purchase_id: uuid.UUID, payload: PurchaseUpdate) -> Purchase:
    p = _require_purchase(db, user, purchase_id)
    fields = payload.model_fields_set
    if not fields & set(_EDITABLE):
        raise AppError(ErrorCode.empty_patch)
    for name in _NOT_NULLABLE:
        if name in fields and getattr(payload, name) is None:
            raise AppError(ErrorCode.field_not_nullable, field=name)

    def final(name):
        return getattr(payload, name) if name in fields else getattr(p, name)

    require_holdable_currency(db, user, final("currency_id"))
    _validate_amount(final("amount"))
    _validate_credit_card(db, user, final("credit_card_id"))
    _validate_category(db, final("category_id"))
    for name in fields & set(_EDITABLE):
        value = getattr(payload, name)
        if name == "description":
            value = _clean_description(value)
        setattr(p, name, value)
    db.flush()
    db.commit()
    db.refresh(p)
    return p
```

En `backend/app/routers/purchases.py`: agregar `import uuid` arriba, `PurchaseUpdate` al import de schemas, y:

```python
@router.patch("/purchases/{purchase_id}", response_model=PurchaseOut)
def update_purchase(
    purchase_id: uuid.UUID,
    payload: PurchaseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PurchaseOut:
    return PurchaseOut.from_model(purchase_service.update_purchase(db, user, purchase_id, payload))
```

- [ ] **Step 5.4: Verificar que pasan**

Run: `pytest tests/test_purchases.py -q`
Expected: todos verdes

- [ ] **Step 5.5: Commit**

```bash
git add app/services/purchase_service.py app/routers/purchases.py tests/test_purchases.py
git commit -m "feat: PATCH /purchases parcial con model_fields_set"
```

---

### Task 6: `DELETE /purchases/{purchase_id}`

**Files:**
- Modify: `backend/app/services/purchase_service.py`
- Modify: `backend/app/routers/purchases.py`
- Test: `backend/tests/test_purchases.py` (agregar)

- [ ] **Step 6.1: Escribir los tests (fallan)**

Agregar a `backend/tests/test_purchases.py`:

```python
def test_delete_hard(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    created = _created(client, headers)
    r = client.delete(f"/purchases/{created['id']}", headers=headers)
    assert r.status_code == 204
    assert client.get("/purchases", headers=headers).json()["purchases"] == []


def test_delete_foreign_404(client, db_session, seed_uy_currency):
    _, headers = _register(db_session, client)
    _, other_headers = _register(db_session, client, email="otro@b.com")
    created = _created(client, headers)
    assert client.delete(f"/purchases/{created['id']}", headers=other_headers).status_code == 404
```

- [ ] **Step 6.2: Verificar que fallan**

Run: `pytest tests/test_purchases.py -q`
Expected: los 2 nuevos fallan (405); el resto verde.

- [ ] **Step 6.3: Implementar**

Al final de `backend/app/services/purchase_service.py`:

```python
def delete_purchase(db: Session, user: User, purchase_id: uuid.UUID) -> None:
    p = _require_purchase(db, user, purchase_id)
    db.delete(p)
    db.commit()
```

Al final de `backend/app/routers/purchases.py`:

```python
@router.delete("/purchases/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase(
    purchase_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    purchase_service.delete_purchase(db, user, purchase_id)
```

- [ ] **Step 6.4: Verificar que pasan**

Run: `pytest tests/test_purchases.py -q`
Expected: todos verdes

- [ ] **Step 6.5: Commit**

```bash
git add app/services/purchase_service.py app/routers/purchases.py tests/test_purchases.py
git commit -m "feat: DELETE /purchases (hard-delete)"
```

---

### Task 7: catálogo `purchase_categories` en `GET /bootstrap`

**Files:**
- Modify: `backend/app/schemas/bootstrap.py`
- Modify: `backend/app/services/bootstrap_service.py`
- Test: `backend/tests/test_bootstrap.py` (modificar)

- [ ] **Step 7.1: Extender el test de bootstrap (falla)**

En `backend/tests/test_bootstrap.py`:

1. Agregar el import:

```python
from app.models.purchase_category import PurchaseCategory
```

2. En `CATALOG_KEYS`, sumar `"purchase_categories"`:

```python
CATALOG_KEYS = {
    "currencies", "obligation_types", "income_types", "priority_levels",
    "institutions", "review_finding_codes", "credit_card_networks", "credit_card_item_types",
    "purchase_categories",
}
```

3. En `_seed_catalogs`, dentro del `add_all` grande, agregar:

```python
        PurchaseCategory(id=1, code="comida", name="Comida", emoji="🍔"),
        PurchaseCategory(id=2, code="supermercado", name="Supermercado", emoji="🛒"),
```

4. Agregar el test (mismo estilo que los existentes del archivo):

```python
def test_bootstrap_purchase_categories(client, db_session, seed_uy):
    _seed_catalogs(db_session)
    token = _register_token(client)
    catalogs = client.get("/bootstrap", headers={"Authorization": f"Bearer {token}"}).json()["catalogs"]
    assert catalogs["purchase_categories"] == [
        {"id": 1, "code": "comida", "name": "Comida", "emoji": "🍔"},
        {"id": 2, "code": "supermercado", "name": "Supermercado", "emoji": "🛒"},
    ]
```

- [ ] **Step 7.2: Verificar que falla**

Run: `pytest tests/test_bootstrap.py -q`
Expected: FAIL (la clave `purchase_categories` no existe todavía)

- [ ] **Step 7.3: Implementar**

En `backend/app/schemas/bootstrap.py`, antes de `class Catalogs`:

```python
class PurchaseCategoryOut(_Read):
    id: int
    code: str
    name: str
    emoji: str
```

y en `Catalogs`:

```python
    purchase_categories: list[PurchaseCategoryOut]
```

En `backend/app/services/bootstrap_service.py`: agregar el import

```python
from app.models.purchase_category import PurchaseCategory
```

y en el dict de `build_catalogs`:

```python
        "purchase_categories": list(
            db.execute(select(PurchaseCategory).order_by(PurchaseCategory.id)).scalars()
        ),
```

- [ ] **Step 7.4: Verificar que pasa**

Run: `pytest tests/test_bootstrap.py -q`
Expected: todos verdes

- [ ] **Step 7.5: Commit**

```bash
git add app/schemas/bootstrap.py app/services/bootstrap_service.py tests/test_bootstrap.py
git commit -m "feat: purchase_categories en GET /bootstrap"
```

---

### Task 8: Verificación final

- [ ] **Step 8.1: Suite completa**

Run: `pytest -q`
Expected: TODA la suite verde, sin warnings nuevos.

- [ ] **Step 8.2: Verificación manual de la migración (DB dev)**

```bash
psql -d margin -c "\d purchases"
psql -d margin -tA -c "select id, code, emoji from purchase_categories order by id;"
```

Expected: tabla con FKs e índice `ix_purchases_user_id_purchase_date`; 12 categorías en orden.

- [ ] **Step 8.3: Cierre**

Usar la skill superpowers:finishing-a-development-branch. Convención del repo: **squash-merge** a `main`
(un commit por feature).

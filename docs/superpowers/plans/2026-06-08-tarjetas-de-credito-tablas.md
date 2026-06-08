# Tarjetas de crédito — Tablas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Crear las 6 tablas restantes del subdominio tarjetas de crédito (modelos + una migración + tests de
constraints), en un solo slice.

**Architecture:** Modelos SQLAlchemy 2.0 (`Mapped`/`mapped_column`) en `app/models/`, registrados en
`app/models/__init__.py` en orden de dependencia; los tests arman el schema con `create_all` sobre Postgres
`margin_test` (savepoint por test), así que el índice único parcial y los `ON DELETE CASCADE` se ejercitan de
verdad. Una migración Alembic crea las 6 tablas; el índice parcial `WHERE deleted_at IS NULL` se ajusta a mano
si el autogenerate no lo emite.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Postgres 16 · pytest.

**Spec:** `docs/superpowers/specs/2026-06-08-tarjetas-de-credito-tablas-design.md`

**Branch:** `feat/credit-cards-tablas` (NO trabajar en `main`). Squash-merge al final.

**Convención de comandos (higiene de permisos):** correr siempre desde el backend con
`cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && <cmd>`. Tests con `pytest -q`
(NO pipear a `tail`/`grep`, NO `2>&1`). Git con `git add`/`git commit` planos (NO `git -C`).

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `app/models/credit_card.py` | `CreditCard` (eje; ciclo + `deleted_at` + índice único parcial) |
| `app/models/credit_card_statement.py` | `CreditCardStatement` (UNIQUE de período) |
| `app/models/credit_card_statement_item.py` | `CreditCardStatementItem` (CASCADE) |
| `app/models/credit_card_purchase.py` | `CreditCardPurchase` (autocompletado) |
| `app/models/staging_credit_card.py` | `StagingCreditCard` (madre; ciclo + `UNIQUE(user_id)`) |
| `app/models/staging_credit_card_item.py` | `StagingCreditCardItem` (CASCADE) |
| `app/models/__init__.py` | Registrar las 6 clases en orden de dependencia |
| `tests/conftest.py` | Fixture `seed_cc_refs` (catálogos + institución + currency + user) |
| `tests/test_credit_cards_model.py` … (6 files) | Tests de inserción/constraints, uno por tabla |
| `alembic/versions/<rev>_create_credit_card_tables.py` | Una migración con las 6 tablas |

---

## Task 0: Crear la rama

- [ ] **Step 1: Branch desde main**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/credit-cards-tablas
```

---

## Task 1: Fixture compartido `seed_cc_refs`

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Agregar el fixture al final de `tests/conftest.py`**

```python
@pytest.fixture
def seed_cc_refs(db_session, seed_uy_currency):
    """UY + Peso (id=1) + institución, red y tipo de ítem (id=1) + un usuario. Devuelve el usuario."""
    from app.models.credit_card_item_type import CreditCardItemType
    from app.models.credit_card_network import CreditCardNetwork
    from app.models.institution import Institution
    from app.models.user import User

    db_session.add_all(
        [
            Institution(id=1, country_code="UY", name="Scotiabank", visible=True),
            CreditCardNetwork(id=1, country_code="UY", code="amex", name="Amex"),
            CreditCardItemType(id=1, code="compra", name="Compra", description="x"),
        ]
    )
    db_session.flush()
    user = User(country_code="UY")
    db_session.add(user)
    db_session.flush()
    return user
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add tests/conftest.py && git commit -m "test: fixture seed_cc_refs para tablas de tarjetas"
```

---

## Task 2: `credit_cards`

**Files:**
- Create: `app/models/credit_card.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_credit_cards_model.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_credit_cards_model.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.credit_card import CreditCard


def _card_kwargs(user):
    return dict(
        user_id=user.id,
        institution_id=1,
        card_network_id=1,
        current_limit=Decimal("150000.00"),
        closing_day=13,
        financing_rate_local=Decimal("69.98"),
        overdue_rate_local=Decimal("81.27"),
        financing_rate_usd=Decimal("13.50"),
        overdue_rate_usd=Decimal("15.68"),
        rates_add_vat=True,
        review_findings="[]",
        is_ready=False,
    )


def test_insert_and_read(db_session, seed_cc_refs):
    user = seed_cc_refs
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    db_session.refresh(card)
    assert card.id is not None
    assert card.closing_day == 13
    assert card.financing_rate_local == Decimal("69.98")
    assert card.created_at is not None
    assert card.deleted_at is None


def test_partial_unique_blocks_two_active(db_session, seed_cc_refs):
    user = seed_cc_refs
    db_session.add(CreditCard(**_card_kwargs(user)))
    db_session.flush()
    db_session.add(CreditCard(**_card_kwargs(user)))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_soft_deleted_does_not_block(db_session, seed_cc_refs):
    user = seed_cc_refs
    deleted = CreditCard(**_card_kwargs(user), deleted_at=datetime.now(timezone.utc))
    db_session.add(deleted)
    db_session.flush()
    active = CreditCard(**_card_kwargs(user))  # misma combinación, vigente
    db_session.add(active)
    db_session.flush()  # no debe romper: el índice parcial solo cuenta deleted_at IS NULL
    db_session.refresh(active)
    assert active.id is not None


def test_invalid_institution_fk(db_session, seed_cc_refs):
    user = seed_cc_refs
    kwargs = _card_kwargs(user)
    kwargs["institution_id"] = 999
    db_session.add(CreditCard(**kwargs))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_not_null_review_findings(db_session, seed_cc_refs):
    user = seed_cc_refs
    kwargs = _card_kwargs(user)
    del kwargs["review_findings"]
    db_session.add(CreditCard(**kwargs))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Run → rojo** (`ModuleNotFoundError: app.models.credit_card`)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_model.py -q
```

- [ ] **Step 3: Crear el modelo**

```python
# app/models/credit_card.py
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCard(Base):
    __tablename__ = "credit_cards"
    __table_args__ = (
        Index(
            "uq_credit_cards_user_institution_network",
            "user_id",
            "institution_id",
            "card_network_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    institution_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("institutions.id"), nullable=False
    )
    card_network_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("credit_card_networks.id"), nullable=False
    )
    current_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    closing_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    financing_rate_local: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    overdue_rate_local: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    financing_rate_usd: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    overdue_rate_usd: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_findings: Mapped[str] = mapped_column(Text, nullable=False)
    user_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Registrar en `app/models/__init__.py`** — agregar después de `CreditCardItemType`:

```python
from app.models.credit_card import CreditCard  # noqa: F401
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_cards_model.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/credit_card.py app/models/__init__.py tests/test_credit_cards_model.py && git commit -m "feat: modelo credit_cards"
```

---

## Task 3: `credit_card_statements`

**Files:**
- Create: `app/models/credit_card_statement.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_credit_card_statements_model.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_credit_card_statements_model.py
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement

from tests.test_credit_cards_model import _card_kwargs


def _make_card(db_session, user):
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    return card


def _statement_kwargs(card):
    return dict(
        credit_card_id=card.id,
        issue_year=2026,
        issue_month=5,
        closing_date=date(2026, 5, 13),
        due_date=date(2026, 5, 25),
        total_local=Decimal("7991.28"),
        total_usd=Decimal("65.35"),
        minimum_payment_local=Decimal("600.00"),
        minimum_payment_usd=Decimal("0.00"),
    )


def test_insert_and_read(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    st = CreditCardStatement(**_statement_kwargs(card))
    db_session.add(st)
    db_session.flush()
    db_session.refresh(st)
    assert st.id is not None
    assert st.total_local == Decimal("7991.28")


def test_unique_period(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    db_session.add(CreditCardStatement(**_statement_kwargs(card)))
    db_session.flush()
    db_session.add(CreditCardStatement(**_statement_kwargs(card)))  # mismo período
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statements_model.py -q
```

- [ ] **Step 3: Crear el modelo**

```python
# app/models/credit_card_statement.py
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCardStatement(Base):
    __tablename__ = "credit_card_statements"
    __table_args__ = (
        UniqueConstraint(
            "credit_card_id", "issue_month", "issue_year", name="uq_credit_card_statements_period"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_cards.id"), nullable=False
    )
    issue_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    issue_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    closing_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_local: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    minimum_payment_local: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    minimum_payment_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar en `__init__.py`** — después de `CreditCard`:

```python
from app.models.credit_card_statement import CreditCardStatement  # noqa: F401
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statements_model.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/credit_card_statement.py app/models/__init__.py tests/test_credit_card_statements_model.py && git commit -m "feat: modelo credit_card_statements"
```

---

## Task 4: `credit_card_statement_items`

**Files:**
- Create: `app/models/credit_card_statement_item.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_credit_card_statement_items_model.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_credit_card_statement_items_model.py
from datetime import date
from decimal import Decimal

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem

from tests.test_credit_cards_model import _card_kwargs
from tests.test_credit_card_statements_model import _statement_kwargs


def _make_statement(db_session, user):
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    st = CreditCardStatement(**_statement_kwargs(card))
    db_session.add(st)
    db_session.flush()
    return st


def _item_kwargs(st, **over):
    base = dict(
        credit_card_statement_id=st.id,
        charge_date=date(2026, 2, 2),
        description="SPORTLINE PUNTA",
        amount=Decimal("1997.50"),
        currency_id=1,
        current_installment=3,
        total_installments=4,
        item_type_id=1,
    )
    base.update(over)
    return base


def test_insert_installment_and_one_payment(db_session, seed_cc_refs):
    st = _make_statement(db_session, seed_cc_refs)
    cuotas = CreditCardStatementItem(**_item_kwargs(st))
    unico = CreditCardStatementItem(
        **_item_kwargs(st, current_installment=None, total_installments=None)
    )
    db_session.add_all([cuotas, unico])
    db_session.flush()
    db_session.refresh(cuotas)
    db_session.refresh(unico)
    assert cuotas.total_installments == 4
    assert unico.current_installment is None


def test_cascade_delete_with_statement(db_session, seed_cc_refs):
    st = _make_statement(db_session, seed_cc_refs)
    st_id = st.id
    db_session.add(CreditCardStatementItem(**_item_kwargs(st)))
    db_session.flush()
    db_session.delete(st)
    db_session.flush()
    remaining = (
        db_session.query(CreditCardStatementItem)
        .filter_by(credit_card_statement_id=st_id)
        .count()
    )
    assert remaining == 0
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statement_items_model.py -q
```

- [ ] **Step 3: Crear el modelo** (FK con `ondelete="CASCADE"`)

```python
# app/models/credit_card_statement_item.py
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCardStatementItem(Base):
    __tablename__ = "credit_card_statement_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_card_statement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credit_card_statements.id", ondelete="CASCADE"),
        nullable=False,
    )
    charge_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    current_installment: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    item_type_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("credit_card_item_types.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar en `__init__.py`** — después de `CreditCardStatement`:

```python
from app.models.credit_card_statement_item import CreditCardStatementItem  # noqa: F401
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_statement_items_model.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/credit_card_statement_item.py app/models/__init__.py tests/test_credit_card_statement_items_model.py && git commit -m "feat: modelo credit_card_statement_items (CASCADE)"
```

---

## Task 5: `credit_card_purchases`

**Files:**
- Create: `app/models/credit_card_purchase.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_credit_card_purchases_model.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_credit_card_purchases_model.py
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.credit_card import CreditCard
from app.models.credit_card_purchase import CreditCardPurchase

from tests.test_credit_cards_model import _card_kwargs


def _make_card(db_session, user):
    card = CreditCard(**_card_kwargs(user))
    db_session.add(card)
    db_session.flush()
    return card


def _purchase_kwargs(card, **over):
    base = dict(
        credit_card_id=card.id,
        description="Heladera",
        charge_date=date(2026, 1, 10),
        amount=Decimal("1997.50"),
        currency_id=1,
        total_installments=12,
        item_type_id=1,
        last_statement_closing_date=date(2026, 5, 13),
    )
    base.update(over)
    return base


def test_insert_installments_and_one_payment(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    cuotas = CreditCardPurchase(**_purchase_kwargs(card))
    unico = CreditCardPurchase(**_purchase_kwargs(card, total_installments=None))
    db_session.add_all([cuotas, unico])
    db_session.flush()
    db_session.refresh(cuotas)
    db_session.refresh(unico)
    assert cuotas.total_installments == 12
    assert unico.total_installments is None


def test_invalid_card_fk(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    import uuid

    db_session.add(CreditCardPurchase(**_purchase_kwargs(card, credit_card_id=uuid.uuid4())))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_purchases_model.py -q
```

- [ ] **Step 3: Crear el modelo**

```python
# app/models/credit_card_purchase.py
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCardPurchase(Base):
    __tablename__ = "credit_card_purchases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_cards.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    charge_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    item_type_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("credit_card_item_types.id"), nullable=False
    )
    last_statement_closing_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar en `__init__.py`** — después de `CreditCardStatementItem`:

```python
from app.models.credit_card_purchase import CreditCardPurchase  # noqa: F401
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_credit_card_purchases_model.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/credit_card_purchase.py app/models/__init__.py tests/test_credit_card_purchases_model.py && git commit -m "feat: modelo credit_card_purchases"
```

---

## Task 6: `staging_credit_cards`

**Files:**
- Create: `app/models/staging_credit_card.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_staging_credit_cards_model.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_staging_credit_cards_model.py
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.staging_credit_card import StagingCreditCard


def _minimal_kwargs(user):
    """Madre mínima: casi todo NULL; solo ciclo NOT NULL + user."""
    return dict(user_id=user.id, review_findings="[]", is_ready=False)


def test_insert_minimal_and_read(db_session, seed_cc_refs):
    user = seed_cc_refs
    madre = StagingCreditCard(**_minimal_kwargs(user))
    db_session.add(madre)
    db_session.flush()
    db_session.refresh(madre)
    assert madre.id is not None
    assert madre.institution_id is None
    assert madre.total_local is None
    assert madre.rates_add_vat is None
    assert madre.created_at is not None


def test_unique_user(db_session, seed_cc_refs):
    user = seed_cc_refs
    db_session.add(StagingCreditCard(**_minimal_kwargs(user)))
    db_session.flush()
    db_session.add(StagingCreditCard(**_minimal_kwargs(user)))  # segundo staging mismo user
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_staging_credit_cards_model.py -q
```

- [ ] **Step 3: Crear el modelo** (datos del resumen nullable; ciclo NOT NULL; `UNIQUE(user_id)`)

```python
# app/models/staging_credit_card.py
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StagingCreditCard(Base):
    __tablename__ = "staging_credit_cards"
    __table_args__ = (UniqueConstraint("user_id", name="uq_staging_credit_cards_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    institution_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("institutions.id"), nullable=True
    )
    card_network_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("credit_card_networks.id"), nullable=True
    )
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_local: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    minimum_payment_local: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    minimum_payment_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    financing_rate_local: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate_local: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    financing_rate_usd: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate_usd: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    rates_add_vat: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_findings: Mapped[str] = mapped_column(Text, nullable=False)
    user_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar en `__init__.py`** — después de `CreditCardPurchase`:

```python
from app.models.staging_credit_card import StagingCreditCard  # noqa: F401
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_staging_credit_cards_model.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/staging_credit_card.py app/models/__init__.py tests/test_staging_credit_cards_model.py && git commit -m "feat: modelo staging_credit_cards"
```

---

## Task 7: `staging_credit_card_items`

**Files:**
- Create: `app/models/staging_credit_card_item.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_staging_credit_card_items_model.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_staging_credit_card_items_model.py
from app.models.staging_credit_card import StagingCreditCard
from app.models.staging_credit_card_item import StagingCreditCardItem


def _make_madre(db_session, user):
    madre = StagingCreditCard(user_id=user.id, review_findings="[]", is_ready=False)
    db_session.add(madre)
    db_session.flush()
    return madre


def test_insert_incomplete_item(db_session, seed_cc_refs):
    madre = _make_madre(db_session, seed_cc_refs)
    item = StagingCreditCardItem(staging_credit_card_id=madre.id)  # todo lo demás NULL
    db_session.add(item)
    db_session.flush()
    db_session.refresh(item)
    assert item.id is not None
    assert item.charge_date is None
    assert item.item_type_id is None


def test_cascade_delete_with_madre(db_session, seed_cc_refs):
    madre = _make_madre(db_session, seed_cc_refs)
    madre_id = madre.id
    db_session.add(StagingCreditCardItem(staging_credit_card_id=madre.id))
    db_session.flush()
    db_session.delete(madre)
    db_session.flush()
    remaining = (
        db_session.query(StagingCreditCardItem).filter_by(staging_credit_card_id=madre_id).count()
    )
    assert remaining == 0
```

- [ ] **Step 2: Run → rojo**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_staging_credit_card_items_model.py -q
```

- [ ] **Step 3: Crear el modelo** (todo nullable salvo FK madre; `ondelete="CASCADE"`)

```python
# app/models/staging_credit_card_item.py
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StagingCreditCardItem(Base):
    __tablename__ = "staging_credit_card_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staging_credit_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staging_credit_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    charge_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("currencies.id"), nullable=True
    )
    current_installment: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    item_type_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("credit_card_item_types.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Registrar en `__init__.py`** — después de `StagingCreditCard`:

```python
from app.models.staging_credit_card_item import StagingCreditCardItem  # noqa: F401
```

- [ ] **Step 5: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_staging_credit_card_items_model.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/models/staging_credit_card_item.py app/models/__init__.py tests/test_staging_credit_card_items_model.py && git commit -m "feat: modelo staging_credit_card_items (CASCADE)"
```

---

## Task 8: Migración Alembic (una, las 6 tablas)

**Files:**
- Create: `alembic/versions/<rev>_create_credit_card_tables.py` (autogenerada)

- [ ] **Step 1: Autogenerar**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create credit card tables"
```

- [ ] **Step 2: Revisar el archivo generado.** Verificar (y ajustar a mano si falta):
  - Las 6 tablas se crean en orden de dependencia (`credit_cards` antes de statements/purchases;
    `credit_card_statements` antes de sus items; `staging_credit_cards` antes de sus items).
  - Los dos FK de items llevan `ondelete='CASCADE'` (`sa.ForeignKeyConstraint(..., ondelete='CASCADE')`).
  - `uq_credit_card_statements_period` y `uq_staging_credit_cards_user_id` presentes.
  - **El índice único parcial** `uq_credit_cards_user_institution_network` se emite con
    `postgresql_where=sa.text('deleted_at IS NULL')`. Si el autogenerate lo omitió o lo generó sin el
    `WHERE`, corregir a mano para que quede:

```python
op.create_index(
    "uq_credit_cards_user_institution_network",
    "credit_cards",
    ["user_id", "institution_id", "card_network_id"],
    unique=True,
    postgresql_where=sa.text("deleted_at IS NULL"),
)
```

  - El `downgrade()` dropea las 6 tablas en orden inverso.

- [ ] **Step 3: Aplicar en la base dev**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic upgrade head
```

Expected: corre limpio, sin error.

- [ ] **Step 4: Verificar reversibilidad (round-trip)**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic downgrade -1 && alembic upgrade head
```

Expected: baja y vuelve a subir sin error.

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add alembic/versions/ && git commit -m "feat: migración create credit card tables"
```

---

## Task 9: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (los ~229 previos + los nuevos de tarjetas).

- [ ] **Step 2: Cierre del branch.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch.
  Presentar opciones (merge local / PR / mantener / descartar). Por la convención del proyecto, el cierre
  esperado es **squash-merge** de `feat/credit-cards-tablas` a `main` (1 commit). El push a origin es
  **manual** — solo cuando el usuario lo pida explícitamente.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** las 6 tablas tienen task (2–7) con su modelo + tests de los constraints del §3/§6
  (índice parcial, UNIQUE de período, UNIQUE user, dos CASCADE, NOT NULL del ciclo, FKs). La migración (8)
  cubre §5. ✓
- **Sin placeholders:** todo el código de modelos, tests y el fix del índice parcial está completo. ✓
- **Consistencia de tipos/nombres:** los helpers `_card_kwargs`/`_statement_kwargs`/`_item_kwargs` se importan
  entre test files con esos nombres exactos; los nombres de constraint (`uq_credit_cards_user_institution_network`,
  `uq_credit_card_statements_period`, `uq_staging_credit_cards_user_id`) coinciden entre modelo y migración. ✓

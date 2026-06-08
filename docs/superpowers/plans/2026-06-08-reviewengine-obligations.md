# ReviewEngine.obligations (reviewer) — Plan de implementación

> **For agentic workers:** Ejecutar según el modo que elija el usuario (inline o subagente con higiene de
> comandos: `cd` no `git -C`, sin `2>&1`). TDD: test → rojo → implementación → verde → commit por task.

**Goal:** Crear `review_obligation` — el reviewer que chequea 2 reglas de tasas sobre una `obligations` y
aplica la transición del ciclo (`reviewed_at`, `review_findings`, `is_ready`, reset de
`user_acknowledged_at`). Solo el reviewer; sin endpoints.

**Architecture:** Función pura en `app/services/review/obligations.py`: relee la obligación con
`SELECT ... FOR UPDATE`, computa los findings (codes ordenados sin duplicados), aplica la transición y
`flush` sin commit. Reviewer incondicional al invocarse (la cola/reset es del endpoint).

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, pytest. Spec:
`docs/superpowers/specs/2026-06-08-reviewengine-obligations-design.md`.

**Rama:** `feat/review-obligations` → squash-merge a `main`.

---

## Task 0: Crear la rama

- [ ] **Step 1:**

```bash
git checkout -b feat/review-obligations
```

---

## Task 1: Reviewer `review_obligation` + tests

**Files:**
- Create: `backend/app/services/review/__init__.py` (vacío)
- Create: `backend/app/services/review/obligations.py`
- Test: `backend/tests/test_review_obligations.py`

- [ ] **Step 1: Escribir los tests (rojo)**

`backend/tests/test_review_obligations.py`:

```python
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.obligation import Obligation
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.user import User
from app.services.review.obligations import review_obligation


@pytest.fixture
def user(db_session, seed_uy_currency):
    db_session.add(PriorityLevel(level=4, name="Prioritaria", description="x"))
    db_session.flush()
    db_session.add(
        ObligationType(id=10, obligation_kind="deuda", code="prestamo", name="Préstamo",
                       description="x", default_priority_level=4, visible=True)
    )
    db_session.flush()
    u = User(country_code="UY")
    db_session.add(u)
    db_session.flush()
    return u


def _deuda(db_session, user, **overrides):
    kwargs = dict(
        user_id=user.id,
        obligation_type_id=10,
        priority_level=4,
        currency_id=1,
        amount=Decimal("5000.00"),
        is_monthly_recurring=False,
        due_day=10,
        first_due_date=date(2026, 7, 1),
        total_installments=12,
        financing_rate=None,
        overdue_rate=None,
        rates_add_vat=True,
        shift_weekends=False,
        is_closed=False,
        review_findings="[]",
        is_ready=False,
    )
    kwargs.update(overrides)
    o = Obligation(**kwargs)
    db_session.add(o)
    db_session.flush()
    return o


def test_sin_findings(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("50.00"), overdue_rate=Decimal("60.00"))
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.review_findings == "[]"
    assert o.is_ready is True
    assert o.reviewed_at is not None


def test_overdue_lower_than_financing(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("50.00"), overdue_rate=Decimal("30.00"))
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert "overdue_lower_than_financing" in json.loads(o.review_findings)
    assert o.is_ready is False


def test_rate_above_threshold(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("160.00"), overdue_rate=None)
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert json.loads(o.review_findings) == ["rate_above_threshold"]
    assert o.is_ready is False


def test_dos_reglas_ordenadas_sin_duplicados(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("200.00"), overdue_rate=Decimal("10.00"))
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    codes = json.loads(o.review_findings)
    assert codes == ["overdue_lower_than_financing", "rate_above_threshold"]
    assert o.is_ready is False


def test_tasas_null_sin_findings(db_session, user):
    o = _deuda(db_session, user, financing_rate=None, overdue_rate=None)
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.review_findings == "[]"
    assert o.is_ready is True


def test_overdue_lower_requiere_ambas(db_session, user):
    # solo financing con valor (overdue NULL) → no dispara overdue_lower ni rate_above
    o = _deuda(db_session, user, financing_rate=Decimal("50.00"), overdue_rate=None)
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.review_findings == "[]"
    assert o.is_ready is True


def test_reset_acknowledge_con_findings(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("200.00"))
    o.user_acknowledged_at = datetime.now(timezone.utc)
    db_session.flush()
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.user_acknowledged_at is None
    assert o.is_ready is False


def test_mantiene_acknowledge_sin_findings(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("50.00"), overdue_rate=Decimal("60.00"))
    ack = datetime.now(timezone.utc)
    o.user_acknowledged_at = ack
    db_session.flush()
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    assert o.user_acknowledged_at is not None


def test_review_findings_es_json_lista(db_session, user):
    o = _deuda(db_session, user, financing_rate=Decimal("200.00"), overdue_rate=Decimal("10.00"))
    review_obligation(db_session, o.id)
    db_session.refresh(o)
    parsed = json.loads(o.review_findings)
    assert isinstance(parsed, list)
    assert all(isinstance(c, str) for c in parsed)
```

- [ ] **Step 2: Correr los tests, verificar que fallan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_review_obligations.py -q
```
Esperado: FAIL (ModuleNotFoundError: app.services.review.obligations).

- [ ] **Step 3: Crear el paquete e implementar el reviewer**

Crear `backend/app/services/review/__init__.py` **vacío**.

`backend/app/services/review/obligations.py`:

```python
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.obligation import Obligation

RATE_THRESHOLD = 150


def _findings(obligation: Obligation) -> list[str]:
    """Codes de los chequeos que dispara la obligación (ordenados, sin duplicados)."""
    codes: list[str] = []
    fin = obligation.financing_rate
    over = obligation.overdue_rate

    if fin is not None and over is not None and over < fin:
        codes.append("overdue_lower_than_financing")
    if (fin is not None and fin > RATE_THRESHOLD) or (over is not None and over > RATE_THRESHOLD):
        codes.append("rate_above_threshold")

    return sorted(set(codes))


def review_obligation(db: Session, obligation_id: uuid.UUID) -> None:
    """Revisa la obligación y aplica la transición del ciclo de revisión: setea reviewed_at,
    review_findings, is_ready y resetea user_acknowledged_at si hay findings. No hace commit."""
    obligation = db.execute(
        select(Obligation).where(Obligation.id == obligation_id).with_for_update()
    ).scalar_one_or_none()
    if obligation is None:
        return

    findings = _findings(obligation)
    obligation.reviewed_at = datetime.now(timezone.utc)
    obligation.review_findings = json.dumps(findings)
    obligation.is_ready = len(findings) == 0
    if findings:
        obligation.user_acknowledged_at = None  # invalida una aceptación previa

    db.flush()
```

- [ ] **Step 4: Correr los tests, verificar que pasan**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_review_obligations.py -q
```
Esperado: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/review/ backend/tests/test_review_obligations.py
git commit -m "feat: ReviewEngine.obligations (reviewer)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Suite completa

- [ ] **Step 1:**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```
Esperado: PASS (todo verde, +9 nuevos).

---

## Cierre

Tras Task 2 verde: **finishing-a-development-branch** → squash-merge `feat/review-obligations` a `main` →
push (manual/prompteado).

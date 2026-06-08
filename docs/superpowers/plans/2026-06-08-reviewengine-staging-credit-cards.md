# ReviewEngine.staging_credit_cards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar el reviewer `review_staging_credit_card(db, staging_id, *, today=None)` que revisa la
madre del staging, produce los findings y aplica la transición del ciclo de revisión.

**Architecture:** Función de servicio en `app/services/review/staging_credit_cards.py`, espejando
`app/services/review/obligations.py`: bloqueo `with_for_update`, cómputo de findings (5 reglas con guardas de
NULL), transición del ciclo (`reviewed_at`/`review_findings`/`is_ready`/reset de `user_acknowledged_at`),
`db.flush()` sin commit. `today` inyectable para tests deterministas. Helper `_months_ago` calendario-correcto
(sin dateutil).

**Tech Stack:** SQLAlchemy 2.0 · pytest · Postgres (`margin_test`, create_all + savepoint).

**Spec:** `docs/superpowers/specs/2026-06-08-reviewengine-staging-credit-cards-design.md`

**Branch:** `feat/review-staging-credit-cards` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** correr desde `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate
&& <cmd>`. Tests con `pytest -q` (NO pipear a `tail`/`grep`, NO `2>&1`). Git `git add`/`git commit` planos (NO
`git -C`). No push.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `app/services/review/staging_credit_cards.py` | `_months_ago`, `_findings`, `review_staging_credit_card` |
| `tests/test_review_staging_credit_cards.py` | Tests de cada regla, sus guardas, soft-deleted, reset de ack |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/review-staging-credit-cards
```

---

## Task 1: Reviewer + tests (TDD)

**Files:**
- Create: `app/services/review/staging_credit_cards.py`
- Test: `tests/test_review_staging_credit_cards.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_review_staging_credit_cards.py
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.credit_card import CreditCard
from app.models.staging_credit_card import StagingCreditCard
from app.services.review.staging_credit_cards import _months_ago, review_staging_credit_card

from tests.test_credit_cards_model import _card_kwargs

TODAY = date(2026, 6, 8)


def _make_madre(db_session, user, **over):
    fields = dict(user_id=user.id, review_findings="[]", is_ready=False)
    fields.update(over)
    madre = StagingCreditCard(**fields)
    db_session.add(madre)
    db_session.flush()
    return madre


def _make_card(db_session, user, deleted_at=None):
    """credit_cards del usuario para institución 1 + red 1 (igual que _card_kwargs)."""
    card = CreditCard(**_card_kwargs(user), deleted_at=deleted_at)
    db_session.add(card)
    db_session.flush()
    return card


def _findings_of(db_session, madre):
    review_staging_credit_card(db_session, madre.id, today=TODAY)
    db_session.refresh(madre)
    return json.loads(madre.review_findings)


# --- _months_ago ---

def test_months_ago_clamps_day():
    assert _months_ago(date(2026, 6, 8), 12) == date(2025, 6, 8)
    assert _months_ago(date(2026, 2, 29) if False else date(2026, 3, 31), 1) == date(2026, 2, 28)


# --- reviewer ---

def test_empty_madre_only_rates_not_updated(db_session, seed_cc_refs):
    madre = _make_madre(db_session, seed_cc_refs)  # todo NULL salvo ciclo + user
    assert _findings_of(db_session, madre) == ["rates_not_updated"]
    assert madre.is_ready is False
    assert madre.reviewed_at is not None


def test_no_findings(db_session, seed_cc_refs):
    user = seed_cc_refs
    _make_card(db_session, user)  # tarjeta vigente para emisor 1 + red 1
    madre = _make_madre(
        db_session, user,
        institution_id=1, card_network_id=1,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25),
        financing_rate_local=Decimal("1.00"), overdue_rate_local=Decimal("2.00"),
        financing_rate_usd=Decimal("3.00"), overdue_rate_usd=Decimal("4.00"),
        rates_add_vat=True,
    )
    assert _findings_of(db_session, madre) == []
    assert madre.is_ready is True
    assert madre.reviewed_at is not None


def test_closing_after_due(db_session, seed_cc_refs):
    madre = _make_madre(
        db_session, seed_cc_refs,
        closing_date=date(2026, 5, 20), due_date=date(2026, 5, 10),
    )
    assert "closing_after_due" in _findings_of(db_session, madre)


def test_closing_after_due_requires_both(db_session, seed_cc_refs):
    madre = _make_madre(db_session, seed_cc_refs, closing_date=date(2026, 5, 20))  # due_date NULL
    findings = _findings_of(db_session, madre)
    assert "closing_after_due" not in findings
    assert "due_date_in_future" not in findings
    assert "due_date_too_old" not in findings


def test_due_date_in_future_boundary(db_session, seed_cc_refs):
    madre = _make_madre(db_session, seed_cc_refs, due_date=TODAY + timedelta(days=61))
    assert "due_date_in_future" in _findings_of(db_session, madre)
    madre.due_date = TODAY + timedelta(days=60)  # justo en el límite: no dispara
    assert "due_date_in_future" not in _findings_of(db_session, madre)


def test_due_date_too_old_boundary(db_session, seed_cc_refs):
    cutoff = _months_ago(TODAY, 12)  # 2025-06-08
    madre = _make_madre(db_session, seed_cc_refs, due_date=cutoff - timedelta(days=1))
    assert "due_date_too_old" in _findings_of(db_session, madre)
    madre.due_date = cutoff  # justo en el corte: no dispara
    assert "due_date_too_old" not in _findings_of(db_session, madre)


def test_rates_not_updated_one_missing(db_session, seed_cc_refs):
    user = seed_cc_refs
    _make_card(db_session, user)
    madre = _make_madre(
        db_session, user,
        institution_id=1, card_network_id=1,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25),
        financing_rate_local=Decimal("1.00"), overdue_rate_local=Decimal("2.00"),
        financing_rate_usd=None, overdue_rate_usd=Decimal("4.00"),  # una en NULL
        rates_add_vat=True,
    )
    assert "rates_not_updated" in _findings_of(db_session, madre)
    madre.financing_rate_usd = Decimal("3.00")  # completa las 4
    assert "rates_not_updated" not in _findings_of(db_session, madre)


def test_new_card_when_none(db_session, seed_cc_refs):
    madre = _make_madre(db_session, seed_cc_refs, institution_id=1, card_network_id=1)
    assert "new_card" in _findings_of(db_session, madre)


def test_new_card_not_with_soft_deleted(db_session, seed_cc_refs):
    user = seed_cc_refs
    _make_card(db_session, user, deleted_at=datetime.now(timezone.utc))  # soft-deleted
    madre = _make_madre(db_session, user, institution_id=1, card_network_id=1)
    assert "new_card" not in _findings_of(db_session, madre)


def test_new_card_requires_issuer_and_network(db_session, seed_cc_refs):
    madre = _make_madre(db_session, seed_cc_refs, institution_id=1, card_network_id=None)
    assert "new_card" not in _findings_of(db_session, madre)


def test_multiple_findings_sorted_unique(db_session, seed_cc_refs):
    madre = _make_madre(
        db_session, seed_cc_refs,
        institution_id=1, card_network_id=1,  # sin tarjeta -> new_card
        closing_date=date(2026, 5, 20), due_date=date(2026, 5, 10),  # closing_after_due
        # tasas NULL -> rates_not_updated
    )
    findings = _findings_of(db_session, madre)
    assert findings == ["closing_after_due", "new_card", "rates_not_updated"]
    assert findings == sorted(findings)
    assert len(findings) == len(set(findings))
    assert madre.is_ready is False


def test_acknowledge_reset_with_findings(db_session, seed_cc_refs):
    madre = _make_madre(
        db_session, seed_cc_refs, user_acknowledged_at=datetime.now(timezone.utc)
    )  # rates NULL -> habrá findings
    _findings_of(db_session, madre)
    assert madre.user_acknowledged_at is None


def test_acknowledge_kept_without_findings(db_session, seed_cc_refs):
    user = seed_cc_refs
    _make_card(db_session, user)
    ack = datetime.now(timezone.utc)
    madre = _make_madre(
        db_session, user,
        institution_id=1, card_network_id=1,
        closing_date=date(2026, 5, 13), due_date=date(2026, 5, 25),
        financing_rate_local=Decimal("1.00"), overdue_rate_local=Decimal("2.00"),
        financing_rate_usd=Decimal("3.00"), overdue_rate_usd=Decimal("4.00"),
        rates_add_vat=True,
        user_acknowledged_at=ack,
    )
    assert _findings_of(db_session, madre) == []
    assert madre.user_acknowledged_at is not None


def test_review_findings_is_valid_json(db_session, seed_cc_refs):
    madre = _make_madre(db_session, seed_cc_refs)
    findings = _findings_of(db_session, madre)
    assert isinstance(findings, list)
    assert all(isinstance(c, str) for c in findings)


def test_missing_row_is_noop(db_session, seed_cc_refs):
    review_staging_credit_card(db_session, uuid.uuid4(), today=TODAY)  # no existe -> no error
```

- [ ] **Step 2: Run → rojo** (`ModuleNotFoundError: app.services.review.staging_credit_cards`)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_review_staging_credit_cards.py -q
```

- [ ] **Step 3: Crear el reviewer**

```python
# app/services/review/staging_credit_cards.py
import calendar
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.credit_card import CreditCard
from app.models.staging_credit_card import StagingCreditCard

DUE_DATE_FUTURE_DAYS = 60
DUE_DATE_OLD_MONTHS = 12


def _months_ago(d: date, months: int) -> date:
    """`d` menos `months` meses, con clamp de día (ej. 31/3 - 1m -> 28/2)."""
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _findings(db: Session, staging: StagingCreditCard, today: date) -> list[str]:
    """Codes de los chequeos que dispara la madre (ordenados, sin duplicados). Cada regla con su
    guarda de NULL: la madre entra incompleta."""
    codes: list[str] = []

    closing = staging.closing_date
    due = staging.due_date

    if closing is not None and due is not None and closing > due:
        codes.append("closing_after_due")
    if due is not None and due > today + timedelta(days=DUE_DATE_FUTURE_DAYS):
        codes.append("due_date_in_future")
    if due is not None and due < _months_ago(today, DUE_DATE_OLD_MONTHS):
        codes.append("due_date_too_old")

    rates = (
        staging.financing_rate_local,
        staging.overdue_rate_local,
        staging.financing_rate_usd,
        staging.overdue_rate_usd,
    )
    if any(r is None for r in rates) or staging.rates_add_vat is None:
        codes.append("rates_not_updated")

    if staging.institution_id is not None and staging.card_network_id is not None:
        # incluye soft-deleted: el promote reactiva una tarjeta borrada en vez de crear otra.
        exists = db.execute(
            select(CreditCard.id).where(
                CreditCard.user_id == staging.user_id,
                CreditCard.institution_id == staging.institution_id,
                CreditCard.card_network_id == staging.card_network_id,
            )
        ).first()
        if exists is None:
            codes.append("new_card")

    return sorted(set(codes))


def review_staging_credit_card(
    db: Session, staging_credit_card_id: uuid.UUID, *, today: date | None = None
) -> None:
    """Revisa la madre del staging y aplica la transición del ciclo de revisión: setea reviewed_at,
    review_findings, is_ready y resetea user_acknowledged_at si hay findings. No hace commit."""
    if today is None:
        today = date.today()

    staging = db.execute(
        select(StagingCreditCard)
        .where(StagingCreditCard.id == staging_credit_card_id)
        .with_for_update()
    ).scalar_one_or_none()
    if staging is None:
        return

    findings = _findings(db, staging, today)
    staging.reviewed_at = datetime.now(timezone.utc)
    staging.review_findings = json.dumps(findings)
    staging.is_ready = len(findings) == 0
    if findings:
        staging.user_acknowledged_at = None  # invalida una aceptación previa

    db.flush()
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_review_staging_credit_cards.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/review/staging_credit_cards.py tests/test_review_staging_credit_cards.py && git commit -m "feat: ReviewEngine.staging_credit_cards (reviewer)"
```

---

## Task 2: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (298 previos + los nuevos del reviewer).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/review-staging-credit-cards` a `main` (1 commit). Push a origin **manual** — solo
  cuando el usuario lo pida.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** las 5 reglas tienen test (incluidas las guardas de NULL y los boundaries de fecha),
  el caso `new_card` con soft-deleted, el `_months_ago`, el reset de acknowledge (con y sin findings), JSON
  válido y el no-op de fila inexistente. ✓
- **Sin placeholders:** todo el código del reviewer y del test file está completo. ✓
- **Consistencia de nombres:** `review_staging_credit_card`, `_months_ago`, `_findings` coinciden entre impl,
  test e imports; reusa `seed_cc_refs` (conftest) y `_card_kwargs` (`tests/test_credit_cards_model.py`). ✓

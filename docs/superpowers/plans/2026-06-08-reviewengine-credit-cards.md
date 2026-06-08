# ReviewEngine.credit_cards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implementar `review_credit_card(db, credit_card_id)` que revisa la tarjeta definitiva, produce los
findings (`closing_day_inferred` / `closing_day_changed`) y aplica la transición del ciclo de revisión.

**Architecture:** Función de servicio en `app/services/review/credit_cards.py`, espejando
`app/services/review/staging_credit_cards.py`: bloqueo `with_for_update`, cómputo de findings (2 reglas
mutuamente excluyentes según `created_at == updated_at`), transición del ciclo, `db.flush()` sin commit. La
regla `closing_day_changed` compara contra el último resumen (`_latest_statement_closing_day`). Sin `today`.

**Tech Stack:** SQLAlchemy 2.0 · pytest · Postgres (`margin_test`, create_all + savepoint).

**Spec:** `docs/superpowers/specs/2026-06-08-reviewengine-credit-cards-design.md`

**Branch:** `feat/review-credit-cards` (NO trabajar en `main`). Squash-merge al final.

**Higiene de comandos:** correr desde `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate
&& <cmd>`. Tests con `pytest -q` (NO pipear a `tail`/`grep`, NO `2>&1`). Git `git add`/`git commit` planos (NO
`git -C`). No push.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `app/services/review/credit_cards.py` | `_latest_statement_closing_day`, `_findings`, `review_credit_card` |
| `tests/test_review_credit_cards.py` | Tests de ambas ramas, boundary, sin resumen, último por período, reset ack |

---

## Task 0: Crear la rama

- [ ] **Step 1**

```bash
cd /Users/tachone/proyectos/margin && git checkout -b feat/review-credit-cards
```

---

## Task 1: Reviewer + tests (TDD)

**Files:**
- Create: `app/services/review/credit_cards.py`
- Test: `tests/test_review_credit_cards.py`

- [ ] **Step 1: Escribir el test (rojo)**

```python
# tests/test_review_credit_cards.py
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement
from app.services.review.credit_cards import _latest_statement_closing_day, review_credit_card

from tests.test_credit_cards_model import _card_kwargs

# Timestamps explícitos para simular una tarjeta "existente" (created_at != updated_at).
# Dentro de una sola transacción no se pueden obtener dos now() distintos, así que se setean a mano.
T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 2, 1, tzinfo=timezone.utc)


def _make_card(db_session, user, *, closing_day=13, created_at=None, updated_at=None):
    kwargs = _card_kwargs(user)
    kwargs["closing_day"] = closing_day
    if created_at is not None:
        kwargs["created_at"] = created_at
    if updated_at is not None:
        kwargs["updated_at"] = updated_at
    card = CreditCard(**kwargs)
    db_session.add(card)
    db_session.flush()
    return card


def _add_statement(db_session, card, *, issue_year=2026, issue_month=5, closing_day=13):
    st = CreditCardStatement(
        credit_card_id=card.id,
        issue_year=issue_year,
        issue_month=issue_month,
        closing_date=date(issue_year, issue_month, closing_day),
        due_date=date(issue_year, issue_month, 25),
        total_local=Decimal("100.00"),
        total_usd=Decimal("0.00"),
        minimum_payment_local=Decimal("10.00"),
        minimum_payment_usd=Decimal("0.00"),
    )
    db_session.add(st)
    db_session.flush()
    return st


def _findings_of(db_session, card):
    review_credit_card(db_session, card.id)
    db_session.refresh(card)
    return json.loads(card.review_findings)


def test_new_card_closing_day_inferred(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)  # server-default -> created_at == updated_at
    findings = _findings_of(db_session, card)
    assert "closing_day_inferred" in findings
    assert card.is_ready is False
    assert card.reviewed_at is not None


def test_new_card_does_not_emit_changed(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs, closing_day=13)
    _add_statement(db_session, card, closing_day=25)  # dif 12, pero la rama existente no corre
    assert _findings_of(db_session, card) == ["closing_day_inferred"]


def test_existing_no_findings(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs, closing_day=13, created_at=T1, updated_at=T2)
    _add_statement(db_session, card, closing_day=13)  # dif 0
    assert _findings_of(db_session, card) == []
    assert card.is_ready is True


def test_existing_closing_day_changed(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs, closing_day=13, created_at=T1, updated_at=T2)
    _add_statement(db_session, card, closing_day=20)  # dif 7 > 4
    findings = _findings_of(db_session, card)
    assert "closing_day_changed" in findings
    assert card.is_ready is False


def test_threshold_boundary(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs, closing_day=13, created_at=T1, updated_at=T2)
    st = _add_statement(db_session, card, closing_day=17)  # dif 4 exacto -> no dispara
    assert "closing_day_changed" not in _findings_of(db_session, card)
    st.closing_date = date(2026, 5, 18)  # dif 5 -> dispara
    db_session.flush()
    assert "closing_day_changed" in _findings_of(db_session, card)


def test_existing_without_statement(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs, closing_day=13, created_at=T1, updated_at=T2)
    assert _findings_of(db_session, card) == []
    assert card.is_ready is True


def test_uses_latest_statement_by_period(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs, closing_day=13, created_at=T1, updated_at=T2)
    _add_statement(db_session, card, issue_year=2026, issue_month=4, closing_day=13)  # dif 0
    _add_statement(db_session, card, issue_year=2026, issue_month=5, closing_day=25)  # dif 12, último
    assert "closing_day_changed" in _findings_of(db_session, card)


def test_acknowledge_reset_with_findings(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs, closing_day=13, created_at=T1, updated_at=T2)
    _add_statement(db_session, card, closing_day=20)  # dif 7 -> finding
    card.user_acknowledged_at = datetime.now(timezone.utc)
    db_session.flush()
    _findings_of(db_session, card)
    assert card.user_acknowledged_at is None


def test_acknowledge_kept_without_findings(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs, closing_day=13, created_at=T1, updated_at=T2)
    _add_statement(db_session, card, closing_day=13)  # dif 0 -> sin finding
    card.user_acknowledged_at = datetime.now(timezone.utc)
    db_session.flush()
    assert _findings_of(db_session, card) == []
    assert card.user_acknowledged_at is not None


def test_review_findings_is_valid_json(db_session, seed_cc_refs):
    card = _make_card(db_session, seed_cc_refs)
    findings = _findings_of(db_session, card)
    assert isinstance(findings, list)
    assert all(isinstance(c, str) for c in findings)


def test_missing_row_is_noop(db_session, seed_cc_refs):
    review_credit_card(db_session, uuid.uuid4())  # no existe -> no error
```

- [ ] **Step 2: Run → rojo** (`ModuleNotFoundError: app.services.review.credit_cards`)

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_review_credit_cards.py -q
```

- [ ] **Step 3: Crear el reviewer**

```python
# app/services/review/credit_cards.py
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.credit_card import CreditCard
from app.models.credit_card_statement import CreditCardStatement

CLOSING_DAY_CHANGE_THRESHOLD = 4


def _latest_statement_closing_day(db: Session, credit_card_id: uuid.UUID) -> int | None:
    """Día del closing_date del último resumen (mayor issue_year, luego issue_month) de la tarjeta.
    None si la tarjeta no tiene resúmenes."""
    closing_date = db.execute(
        select(CreditCardStatement.closing_date)
        .where(CreditCardStatement.credit_card_id == credit_card_id)
        .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
        .limit(1)
    ).scalar_one_or_none()
    return closing_date.day if closing_date is not None else None


def _findings(db: Session, card: CreditCard) -> list[str]:
    """Codes de los chequeos de la tarjeta (ordenados, sin duplicados). Las dos reglas son mutuamente
    excluyentes según created_at == updated_at (recién creada vs existente)."""
    codes: list[str] = []

    if card.created_at == card.updated_at:
        # recién creada: el closing_day se infirió del primer resumen; pedir confirmación.
        codes.append("closing_day_inferred")
    else:
        # existente: ¿el último resumen muestra un día de cierre distinto del vigente?
        statement_day = _latest_statement_closing_day(db, card.id)
        if (
            statement_day is not None
            and abs(statement_day - card.closing_day) > CLOSING_DAY_CHANGE_THRESHOLD
        ):
            codes.append("closing_day_changed")

    return sorted(set(codes))


def review_credit_card(db: Session, credit_card_id: uuid.UUID) -> None:
    """Revisa la tarjeta y aplica la transición del ciclo de revisión: setea reviewed_at, review_findings,
    is_ready y resetea user_acknowledged_at si hay findings. No hace commit."""
    card = db.execute(
        select(CreditCard).where(CreditCard.id == credit_card_id).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        return

    findings = _findings(db, card)
    card.reviewed_at = datetime.now(timezone.utc)
    card.review_findings = json.dumps(findings)
    card.is_ready = len(findings) == 0
    if findings:
        card.user_acknowledged_at = None  # invalida una aceptación previa

    db.flush()
```

- [ ] **Step 4: Run → verde**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest tests/test_review_credit_cards.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin/backend && git add app/services/review/credit_cards.py tests/test_review_credit_cards.py && git commit -m "feat: ReviewEngine.credit_cards (reviewer)"
```

---

## Task 2: Suite completa + cierre

- [ ] **Step 1: Correr toda la suite**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q
```

Expected: todo verde (314 previos + los nuevos del reviewer).

- [ ] **Step 2: Cierre.** REQUIRED SUB-SKILL: usar superpowers:finishing-a-development-branch. Cierre esperado:
  **squash-merge** de `feat/review-credit-cards` a `main` (1 commit). Push a origin **manual** — solo cuando el
  usuario lo pida.

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** ambas reglas (nueva→inferred, existente→changed), la exclusión mutua (nueva no emite
  changed), el boundary del umbral (4 no / 5 sí), el caso sin resumen, el uso del último resumen por período,
  el reset de acknowledge (con/sin findings), JSON válido y el no-op de fila inexistente. ✓
- **Sin placeholders:** todo el código del reviewer y del test file está completo. ✓
- **Consistencia de nombres:** `review_credit_card`, `_latest_statement_closing_day`, `_findings`,
  `CLOSING_DAY_CHANGE_THRESHOLD` coinciden entre impl, test e imports; reusa `seed_cc_refs` y `_card_kwargs`. ✓
- **Nota sobre timestamps en tests:** la tarjeta "existente" usa `created_at`/`updated_at` explícitos porque en
  una sola transacción `now()` es constante; la escritura del ciclo del reviewer bumpea `updated_at` pero se
  lee antes, así que no afecta el resultado. ✓

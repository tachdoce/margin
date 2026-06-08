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

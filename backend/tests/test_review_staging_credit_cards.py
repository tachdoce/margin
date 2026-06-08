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
    assert _months_ago(date(2026, 3, 31), 1) == date(2026, 2, 28)


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

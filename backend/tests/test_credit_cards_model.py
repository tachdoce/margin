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

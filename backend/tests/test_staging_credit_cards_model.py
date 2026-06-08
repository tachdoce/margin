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

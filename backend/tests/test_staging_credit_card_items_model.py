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

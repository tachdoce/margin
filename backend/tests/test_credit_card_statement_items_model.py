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

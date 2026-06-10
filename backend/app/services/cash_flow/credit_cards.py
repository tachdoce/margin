import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cash_flow_entry import CashFlowEntry
from app.models.cash_flow_payment import CashFlowPayment
from app.models.country import Country
from app.models.credit_card import CreditCard
from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_card_statement_item import CreditCardStatementItem
from app.models.user import User
from app.services.cash_flow.constants import PROJECTED_MINIMUM_RATE
from app.services.cash_flow.date_utils import compute_event_date
from app.services.cash_flow.rates import effective_rate
from app.services.scoping import credit_card_usd_currency, legal_tender_currency

HORIZON = date(2027, 12, 31)


def _add_months(year: int, month: int, k: int) -> tuple[int, int]:
    """(year, month) + k meses."""
    idx = (month - 1) + k
    return year + idx // 12, idx % 12 + 1


def _latest_statement(db: Session, credit_card_id: uuid.UUID) -> CreditCardStatement | None:
    """El resumen de mayor (issue_year, issue_month) de la tarjeta. None si no hay."""
    return db.execute(
        select(CreditCardStatement)
        .where(CreditCardStatement.credit_card_id == credit_card_id)
        .order_by(CreditCardStatement.issue_year.desc(), CreditCardStatement.issue_month.desc())
        .limit(1)
    ).scalar_one_or_none()


def _projection_sums(
    db: Session, statement: CreditCardStatement, horizon: date
) -> dict[tuple[int, int, int], Decimal]:
    """{(year, month, currency_id): monto} de cuotas pendientes + suscripciones de los ítems del
    resumen, de M+1 (M = mes del closing_date) al horizonte, agrupadas por mes y moneda."""
    sub_type_id = db.execute(
        select(CreditCardItemType.id).where(CreditCardItemType.code == "suscripcion")
    ).scalar_one_or_none()
    items = db.execute(
        select(CreditCardStatementItem).where(
            CreditCardStatementItem.credit_card_statement_id == statement.id
        )
    ).scalars()

    base_y, base_m = statement.closing_date.year, statement.closing_date.month
    horizon_key = (horizon.year, horizon.month)
    sums: dict[tuple[int, int, int], Decimal] = {}

    def add(k: int, currency_id: int, amount: Decimal) -> bool:
        y, m = _add_months(base_y, base_m, k)
        if (y, m) > horizon_key:
            return False
        key = (y, m, currency_id)
        sums[key] = sums.get(key, Decimal("0")) + amount
        return True

    for item in items:
        if item.current_installment is not None and item.total_installments is not None:
            remaining = item.total_installments - item.current_installment
            for k in range(1, remaining + 1):
                if not add(k, item.currency_id, item.amount):
                    break
        elif sub_type_id is not None and item.item_type_id == sub_type_id:
            k = 1
            while add(k, item.currency_id, item.amount):
                k += 1

    return sums


def _reconcile(
    db: Session, card: CreditCard, targets: dict[tuple[int, int, int], dict], today: date
) -> None:
    """UPSERT del target set por clave (issue_year, issue_month, currency_id) contra las entries
    'tarjeta_credito' de la tarjeta; borra las que quedan fuera solo si son futuras y sin pago real."""
    existing = list(
        db.execute(
            select(CashFlowEntry).where(
                CashFlowEntry.source_type == "tarjeta_credito",
                CashFlowEntry.source_id == card.id,
            )
        ).scalars()
    )
    by_key = {(e.issue_year, e.issue_month, e.currency_id): e for e in existing}

    for (iy, im, cid), f in targets.items():
        entry = by_key.get((iy, im, cid))
        if entry is not None:
            entry.event_date = f["event_date"]
            entry.amount = f["amount"]
            entry.financing_rate = f["financing_rate"]
            entry.overdue_rate = f["overdue_rate"]
            entry.minimum_payment = f["minimum_payment"]
        else:
            db.add(
                CashFlowEntry(
                    user_id=card.user_id,
                    event_date=f["event_date"],
                    is_income=False,
                    amount=f["amount"],
                    currency_id=cid,
                    financing_rate=f["financing_rate"],
                    overdue_rate=f["overdue_rate"],
                    issue_year=iy,
                    issue_month=im,
                    minimum_payment=f["minimum_payment"],
                    source_type="tarjeta_credito",
                    source_id=card.id,
                )
            )

    stale = [e for key, e in by_key.items() if key not in targets]
    if stale:
        paid_ids = set(
            db.execute(
                select(CashFlowPayment.cash_flow_entry_id).where(
                    CashFlowPayment.cash_flow_entry_id.in_([e.id for e in stale]),
                    CashFlowPayment.plan_id.is_(None),
                )
            ).scalars()
        )
        for e in stale:
            if e.event_date is not None and e.event_date >= today:
                if e.id in paid_ids:
                    raise RuntimeError(
                        f"materialize_credit_card: invariante violado, "
                        f"entry {e.id} con pago real quedó fuera del objetivo"
                    )
                db.delete(e)


def materialize_credit_card(
    db: Session, credit_card_id: uuid.UUID, *, today: date | None = None, horizon: date = HORIZON
) -> None:
    """(Re)materializa las cash_flow_entries de una tarjeta. Gate: is_ready False → no-op. No commit.
    Responsabilidad 1: materializa el último resumen (hasta una fila por moneda con total > 0)."""
    if today is None:
        today = date.today()

    card = db.execute(
        select(CreditCard).where(CreditCard.id == credit_card_id).with_for_update()
    ).scalar_one_or_none()
    if card is None:
        return
    if not card.is_ready:
        return  # gate: no-op silencioso

    user = db.get(User, card.user_id)
    vat_rate = db.get(Country, user.country_code).vat_rate
    local_id = legal_tender_currency(db, user).id
    usd_id = credit_card_usd_currency(db, user).id

    fin_local = effective_rate(card.financing_rate_local, card.rates_add_vat, vat_rate)
    over_local = effective_rate(card.overdue_rate_local, card.rates_add_vat, vat_rate)
    fin_usd = effective_rate(card.financing_rate_usd, card.rates_add_vat, vat_rate)
    over_usd = effective_rate(card.overdue_rate_usd, card.rates_add_vat, vat_rate)

    targets: dict[tuple[int, int, int], dict] = {}

    # --- Responsabilidad 1: el último resumen ---
    statement = _latest_statement(db, card.id)
    if statement is not None:
        iy, im = statement.closing_date.year, statement.closing_date.month
        for cid, total, minimum, fin, over in (
            (local_id, statement.total_local, statement.minimum_payment_local, fin_local, over_local),
            (usd_id, statement.total_usd, statement.minimum_payment_usd, fin_usd, over_usd),
        ):
            if total is not None and total > 0:
                targets[(iy, im, cid)] = dict(
                    event_date=statement.due_date,
                    amount=total,
                    financing_rate=fin,
                    overdue_rate=over,
                    minimum_payment=minimum,
                )

    # --- Responsabilidad 2: proyección de meses siguientes ---
    if statement is not None:
        rate_pair = {local_id: (fin_local, over_local), usd_id: (fin_usd, over_usd)}
        for (y, m, cid), amount in _projection_sums(db, statement, horizon).items():
            fin, over = rate_pair.get(cid, (None, None))
            # vence el mismo mes del cierre si due_day >= closing_day; si no, el mes siguiente
            if card.due_day >= card.closing_day:
                dy, dm = y, m
            else:
                dy, dm = _add_months(y, m, 1)
            targets[(y, m, cid)] = dict(
                event_date=compute_event_date(dy, dm, card.due_day, False),
                amount=amount,
                financing_rate=fin,
                overdue_rate=over,
                minimum_payment=(amount * PROJECTED_MINIMUM_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            )

    _reconcile(db, card, targets, today)
    db.flush()

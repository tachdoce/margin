from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.credit_card_item_type import CreditCardItemType
from app.models.credit_card_network import CreditCardNetwork
from app.models.currency import Currency
from app.models.income_type import IncomeType
from app.models.institution import Institution
from app.models.obligation_type import ObligationType
from app.models.priority_level import PriorityLevel
from app.models.purchase_category import PurchaseCategory
from app.models.review_finding_code import ReviewFindingCode
from app.models.user import User


def build_catalogs(db: Session, user: User) -> dict:
    cc = user.country_code
    return {
        "currencies": list(
            db.execute(select(Currency).where(Currency.country_code == cc).order_by(Currency.id)).scalars()
        ),
        "obligation_types": list(
            db.execute(select(ObligationType).where(ObligationType.visible.is_(True)).order_by(ObligationType.id)).scalars()
        ),
        "income_types": list(
            db.execute(select(IncomeType).where(IncomeType.visible.is_(True)).order_by(IncomeType.id)).scalars()
        ),
        "priority_levels": list(
            db.execute(select(PriorityLevel).order_by(PriorityLevel.level)).scalars()
        ),
        "institutions": list(
            db.execute(
                select(Institution).where(Institution.visible.is_(True), Institution.country_code == cc).order_by(Institution.id)
            ).scalars()
        ),
        "review_finding_codes": list(
            db.execute(select(ReviewFindingCode).order_by(ReviewFindingCode.code)).scalars()
        ),
        "credit_card_networks": list(
            db.execute(select(CreditCardNetwork).where(CreditCardNetwork.country_code == cc).order_by(CreditCardNetwork.id)).scalars()
        ),
        "credit_card_item_types": list(
            db.execute(select(CreditCardItemType).order_by(CreditCardItemType.id)).scalars()
        ),
        "purchase_categories": list(
            db.execute(select(PurchaseCategory).order_by(PurchaseCategory.id)).scalars()
        ),
    }

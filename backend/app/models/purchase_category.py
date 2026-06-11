from sqlalchemy import SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PurchaseCategory(Base):
    __tablename__ = "purchase_categories"
    __table_args__ = (UniqueConstraint("code", name="uq_purchase_categories_code"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)

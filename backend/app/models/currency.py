from sqlalchemy import Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Currency(Base):
    __tablename__ = "currencies"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    country_code: Mapped[str] = mapped_column(String(2), ForeignKey("countries.code"), nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    is_legal_tender: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    allowed_in_credit_card: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, server_default="")
    display_decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2")

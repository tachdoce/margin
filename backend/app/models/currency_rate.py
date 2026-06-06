from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CurrencyRate(Base):
    __tablename__ = "currency_rates"

    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    is_projected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

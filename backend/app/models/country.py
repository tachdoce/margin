from decimal import Decimal

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Country(Base):
    __tablename__ = "countries"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default="0")

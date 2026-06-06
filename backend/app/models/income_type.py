from sqlalchemy import Boolean, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IncomeType(Base):
    __tablename__ = "income_types"
    __table_args__ = (UniqueConstraint("code", name="uq_income_types_code"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

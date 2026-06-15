from sqlalchemy import Boolean, Enum, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ObligationType(Base):
    __tablename__ = "obligation_types"
    __table_args__ = (UniqueConstraint("code", name="uq_obligation_types_code"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    obligation_kind: Mapped[str] = mapped_column(
        Enum("gasto", "deuda", "deuda_abierta", name="obligation_kind"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

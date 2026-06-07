import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

CASH_FLOW_SOURCE_TYPES = (
    "gasto",
    "deuda",
    "deuda_abierta",
    "ingreso",
    "plan_movimiento",
    "plan_movimiento_entrada",
    "tarjeta_credito",
)


class CashFlowEntry(Base):
    __tablename__ = "cash_flow_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_income: Mapped[bool] = mapped_column(Boolean, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    financing_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    issue_year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    issue_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    minimum_payment: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    source_type: Mapped[str] = mapped_column(
        Enum(*CASH_FLOW_SOURCE_TYPES, name="cash_flow_source_type"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

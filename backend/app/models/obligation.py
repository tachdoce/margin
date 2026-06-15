import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import PAYMENT_RULE


class Obligation(Base):
    __tablename__ = "obligations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    obligation_type_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("obligation_types.id"), nullable=False
    )
    institution_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("institutions.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_monthly_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False)
    due_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    first_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shift_weekends: Mapped[bool] = mapped_column(Boolean, nullable=False)
    financing_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payment_rule: Mapped[str] = mapped_column(PAYMENT_RULE, nullable=False, server_default="ninguno")
    priority: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    monthly_paydown_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    priority_open_debt: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    origin_obligation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("obligations.id"), nullable=True, index=True
    )
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_findings: Mapped[str] = mapped_column(Text, nullable=False)
    user_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

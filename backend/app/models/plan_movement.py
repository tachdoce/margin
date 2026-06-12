import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PlanMovement(Base):
    __tablename__ = "plan_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    kind: Mapped[str] = mapped_column(
        Enum(
            "ingreso", "deuda_informal", "prestamo", "deuda", "tarjetazo",
            name="plan_movement_kind",
        ),
        nullable=False,
    )
    currency_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("currencies.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    income_duration_months: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    installment_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    installment_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    financing_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

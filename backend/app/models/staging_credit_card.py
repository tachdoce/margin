import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StagingCreditCard(Base):
    __tablename__ = "staging_credit_cards"
    __table_args__ = (UniqueConstraint("user_id", name="uq_staging_credit_cards_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    institution_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("institutions.id"), nullable=True
    )
    card_network_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("credit_card_networks.id"), nullable=True
    )
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_local: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    minimum_payment_local: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    minimum_payment_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    financing_rate_local: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate_local: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    financing_rate_usd: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overdue_rate_usd: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    rates_add_vat: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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

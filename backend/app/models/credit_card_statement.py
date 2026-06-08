import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditCardStatement(Base):
    __tablename__ = "credit_card_statements"
    __table_args__ = (
        UniqueConstraint(
            "credit_card_id", "issue_month", "issue_year", name="uq_credit_card_statements_period"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credit_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_cards.id"), nullable=False
    )
    issue_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    issue_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    closing_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_local: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    minimum_payment_local: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    minimum_payment_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

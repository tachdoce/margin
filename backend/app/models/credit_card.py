import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import PAYMENT_RULE


class CreditCard(Base):
    __tablename__ = "credit_cards"
    __table_args__ = (
        Index(
            "uq_credit_cards_user_institution_network",
            "user_id",
            "institution_id",
            "card_network_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    institution_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("institutions.id"), nullable=False
    )
    card_network_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("credit_card_networks.id"), nullable=False
    )
    current_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    closing_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    due_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    financing_rate_local: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    overdue_rate_local: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    financing_rate_usd: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    overdue_rate_usd: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    rates_add_vat: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payment_rule: Mapped[str] = mapped_column(PAYMENT_RULE, nullable=False, server_default="ninguno")
    priority: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

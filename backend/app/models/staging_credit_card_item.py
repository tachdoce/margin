import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StagingCreditCardItem(Base):
    __tablename__ = "staging_credit_card_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staging_credit_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staging_credit_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    charge_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("currencies.id"), nullable=True
    )
    current_installment: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    total_installments: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    item_type_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("credit_card_item_types.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

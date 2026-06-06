from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ReviewFindingCode(Base):
    __tablename__ = "review_finding_codes"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    message: Mapped[str] = mapped_column(String(200), nullable=False)

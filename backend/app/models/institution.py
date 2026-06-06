from sqlalchemy import Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    country_code: Mapped[str] = mapped_column(String(2), ForeignKey("countries.code"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

# app/services/auth_service.py
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import create_access_token, hash_password, verify_password
from app.models.auth_identity import AuthIdentity
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest

DEFAULT_COUNTRY_CODE = "UY"
MIN_PASSWORD_LENGTH = 8
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def register_user(db: Session, data: RegisterRequest) -> tuple[User, str]:
    if not _EMAIL_RE.match(data.email.strip()):
        raise AppError(ErrorCode.email_invalid, field="email")
    email = data.email.strip().lower()
    if len(data.password) < MIN_PASSWORD_LENGTH:
        raise AppError(ErrorCode.password_too_short, field="password")
    existing = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == "email", AuthIdentity.identifier == email
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError(ErrorCode.email_already_registered, field="email")

    user = User(country_code=DEFAULT_COUNTRY_CODE, display_name=data.display_name)
    db.add(user)
    db.flush()

    identity = AuthIdentity(
        user_id=user.id,
        provider="email",
        identifier=email,
        password_hash=hash_password(data.password),
    )
    db.add(identity)
    db.commit()
    db.refresh(user)

    return user, create_access_token(user.id)


def login_user(db: Session, data: LoginRequest) -> tuple[User, str]:
    email = data.email.strip().lower()
    identity = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == "email", AuthIdentity.identifier == email
        )
    ).scalar_one_or_none()
    if identity is None or identity.password_hash is None:
        raise AppError(ErrorCode.credentials_invalid)
    if not verify_password(data.password, identity.password_hash):
        raise AppError(ErrorCode.credentials_invalid)
    user = db.get(User, identity.user_id)
    if user is None or user.deleted_at is not None:
        raise AppError(ErrorCode.credentials_invalid)
    return user, create_access_token(user.id)

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def resolve_user_from_token(token: str | None, db: Session) -> User:
    """Núcleo testeable: del token al User, o AppError(unauthenticated)."""
    if not token:
        raise AppError(ErrorCode.unauthenticated)
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise AppError(ErrorCode.unauthenticated)
    raw_id = payload.get("user_id")
    try:
        user_id = uuid.UUID(str(raw_id))
    except (ValueError, TypeError):
        raise AppError(ErrorCode.unauthenticated)
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError(ErrorCode.unauthenticated)
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency de FastAPI para rutas protegidas."""
    token = credentials.credentials if credentials else None
    return resolve_user_from_token(token, db)

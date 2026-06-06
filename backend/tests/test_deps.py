import uuid
from datetime import datetime, timezone

import pytest

from app.core.deps import resolve_user_from_token
from app.core.errors import AppError, ErrorCode
from app.core.security import create_access_token
from app.models.user import User


def _make_user(db_session):
    user = User(country_code="UY", display_name="Test")
    db_session.add(user)
    db_session.flush()
    return user


def test_resolve_user_valid_token(db_session, seed_uy):
    user = _make_user(db_session)
    result = resolve_user_from_token(create_access_token(user.id), db_session)
    assert result.id == user.id


def test_resolve_user_no_token(db_session):
    with pytest.raises(AppError) as exc:
        resolve_user_from_token(None, db_session)
    assert exc.value.code == ErrorCode.unauthenticated


def test_resolve_user_invalid_token(db_session):
    with pytest.raises(AppError) as exc:
        resolve_user_from_token("not-a-jwt", db_session)
    assert exc.value.code == ErrorCode.unauthenticated


def test_resolve_user_not_found(db_session):
    # token bien firmado para un id que no existe en la DB
    token = create_access_token(uuid.uuid4())
    with pytest.raises(AppError) as exc:
        resolve_user_from_token(token, db_session)
    assert exc.value.code == ErrorCode.unauthenticated


def test_resolve_user_bad_user_id(db_session):
    # payload con user_id que no es un UUID válido
    token = create_access_token("not-a-uuid")
    with pytest.raises(AppError) as exc:
        resolve_user_from_token(token, db_session)
    assert exc.value.code == ErrorCode.unauthenticated


def test_resolve_user_soft_deleted(db_session, seed_uy):
    user = _make_user(db_session)
    user.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    with pytest.raises(AppError) as exc:
        resolve_user_from_token(create_access_token(user.id), db_session)
    assert exc.value.code == ErrorCode.unauthenticated

# Users + Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar registro y login por email+password (`POST /auth/register`, `POST /auth/login`) con JWT, hashing bcrypt, capa de servicio y un manejo de errores centralizado que respeta el contrato de Notion.

**Architecture:** Router finito → capa de servicio (lógica + validaciones + transacción, lanza `AppError`) → core (`security` para hash/JWT, `errors` para catálogo + handlers). Modelos `users` y `auth_identities` (+ enum `auth_provider`). El plan default del registro queda diferido (no afecta el contrato externo).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Postgres 16, passlib+bcrypt, python-jose, pytest. Python 3.13, venv en `backend/.venv`.

**Spec:** `docs/superpowers/specs/2026-06-06-users-auth-design.md`.

---

## Estructura de archivos

```
backend/app/
├── core/
│   ├── config.py        # + secret_key, jwt_expire_days   (MODIFICAR)
│   ├── security.py       # hash/verify password + crear/decodificar JWT   (NUEVO)
│   └── errors.py         # ErrorCode + AppError + register_error_handlers   (NUEVO)
├── models/
│   ├── user.py           # modelo User   (NUEVO)
│   ├── auth_identity.py   # modelo AuthIdentity + enum auth_provider   (NUEVO)
│   └── __init__.py        # registrar User y AuthIdentity   (MODIFICAR)
├── schemas/
│   └── auth.py           # RegisterRequest, LoginRequest, UserRead, AuthResponse   (NUEVO)
├── services/
│   ├── __init__.py        # (NUEVO, vacío)
│   └── auth_service.py    # register_user, login_user   (NUEVO)
├── routers/
│   └── auth.py           # POST /auth/register, POST /auth/login   (NUEVO)
└── main.py               # montar auth router + register_error_handlers   (MODIFICAR)
backend/tests/
├── conftest.py           # savepoint + fixture seed_uy   (MODIFICAR)
├── test_security.py       # (NUEVO)
├── test_errors.py         # (NUEVO)
├── test_auth_register.py  # (NUEVO)
└── test_auth_login.py     # (NUEVO)
backend/alembic/versions/  # migración users + auth_identities   (NUEVO)
```

---

## Task 1: Dependencias y config

**Files:** Modify `backend/requirements.txt`, `backend/app/core/config.py`, `backend/.env.example`

- [ ] **Step 1: Agregar dependencias a `requirements.txt`**

Agregar al final:

```
passlib==1.7.4
bcrypt==4.0.1
python-jose[cryptography]==3.3.0
```

(`bcrypt` se pinea en 4.0.1 para evitar el warning de detección de versión de passlib con bcrypt ≥ 4.1.)

- [ ] **Step 2: Instalar**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pip install -r requirements.txt`
Expected: "Successfully installed ... bcrypt-4.0.1 passlib-1.7.4 python-jose-3.3.0 ..."

- [ ] **Step 3: Agregar config en `app/core/config.py`**

Agregar estos dos campos dentro de la clase `Settings` (después de `test_database_url`):

```python
    secret_key: str = "dev-insecure-change-me"
    jwt_expire_days: int = 45
```

- [ ] **Step 4: Agregar a `.env.example`**

```
SECRET_KEY=poné-una-clave-larga-y-secreta-acá
JWT_EXPIRE_DAYS=45
```

- [ ] **Step 5: Verificar**

Run: `python -c "from app.core.config import settings; print(settings.jwt_expire_days)"`
Expected: `45`

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/requirements.txt backend/app/core/config.py backend/.env.example
git commit -m "chore(backend): deps y config para auth (passlib, jose, secret_key)"
```

---

## Task 2: core/security.py (hash + JWT) — TDD

**Files:** Create `backend/tests/test_security.py`, `backend/app/core/security.py`

- [ ] **Step 1: Test que falla `tests/test_security.py`**

```python
def test_hash_and_verify_password():
    from app.core.security import hash_password, verify_password

    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_token_roundtrip_contains_user_id():
    from app.core.security import create_access_token, decode_access_token

    token = create_access_token("abc-123")
    payload = decode_access_token(token)
    assert payload["user_id"] == "abc-123"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_security.py -v`
Expected: FALLA (`ModuleNotFoundError: No module named 'app.core.security'`).

- [ ] **Step 3: Implementar `app/core/security.py`**

```python
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {"user_id": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_security.py -v`
Expected: PASAN los dos tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/core/security.py backend/tests/test_security.py
git commit -m "feat(backend): security (hash bcrypt + JWT)"
```

---

## Task 3: core/errors.py + handlers — TDD

**Files:** Create `backend/tests/test_errors.py`, `backend/app/core/errors.py`, Modify `backend/app/main.py`

- [ ] **Step 1: Test que falla `tests/test_errors.py`**

```python
def test_app_error_carries_status_and_message():
    from app.core.errors import AppError, ErrorCode

    err = AppError(ErrorCode.email_already_registered, field="email")
    assert err.code.status_code == 409
    assert err.code.message == "Ese email ya está registrado."
    assert err.field == "email"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_errors.py -v`
Expected: FALLA (`ModuleNotFoundError: No module named 'app.core.errors'`).

- [ ] **Step 3: Implementar `app/core/errors.py`**

```python
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(Enum):
    unauthenticated = (401, "Sesión inválida o expirada.")
    credentials_invalid = (401, "Credenciales inválidas.")
    email_already_registered = (409, "Ese email ya está registrado.")
    email_invalid = (422, "Email inválido.")
    password_too_short = (422, "La contraseña debe tener al menos 8 caracteres.")
    validation_failed = (422, "Hay errores en el formulario.")

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message


class AppError(Exception):
    def __init__(self, code: ErrorCode, field: str | None = None):
        self.code = code
        self.field = field
        super().__init__(code.message)


def _single_body(code: ErrorCode, field: str | None) -> dict:
    body = {"code": code.name, "message": code.message}
    if field is not None:
        body["field"] = field
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.status_code, content=_single_body(exc.code, exc.field))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "code": "field_invalid",
                "message": e.get("msg", "Campo inválido."),
                "field": e["loc"][-1] if e.get("loc") else None,
            }
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "code": ErrorCode.validation_failed.name,
                "message": ErrorCode.validation_failed.message,
                "errors": errors,
            },
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"code": "internal_error", "message": "Ocurrió un error. Intentá de nuevo."},
        )
```

> Nota: para errores de Pydantic individuales se usa el code genérico `field_invalid` dentro del wrapper `validation_failed`. Los codes específicos por campo (de negocio) los lanza el servicio con `AppError`.

- [ ] **Step 4: Correr y verificar que pasa**

Run: `pytest tests/test_errors.py -v`
Expected: PASA.

- [ ] **Step 5: Registrar los handlers en `app/main.py`**

Reemplazar el contenido de `app/main.py` por:

```python
from fastapi import FastAPI

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.routers import countries, health

app = FastAPI(title=settings.app_name)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(countries.router)
```

- [ ] **Step 6: Verificar que toda la suite sigue verde**

Run: `pytest -q`
Expected: pasan todos (health, countries, security, errors).

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/core/errors.py backend/app/main.py backend/tests/test_errors.py
git commit -m "feat(backend): capa de errores (catálogo + AppError + handlers)"
```

---

## Task 4: Modelos users + auth_identities + migración

**Files:** Create `backend/app/models/user.py`, `backend/app/models/auth_identity.py`, Modify `backend/app/models/__init__.py`, Create migración en `backend/alembic/versions/`

- [ ] **Step 1: `app/models/user.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country_code: Mapped[str] = mapped_column(String(2), ForeignKey("countries.code"), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: `app/models/auth_identity.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "identifier", name="uq_auth_identities_provider_identifier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Enum("email", name="auth_provider"), nullable=False)
    identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 3: Registrar los modelos en `app/models/__init__.py`**

```python
from app.models.country import Country  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.auth_identity import AuthIdentity  # noqa: F401
```

- [ ] **Step 4: Autogenerar la migración**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && alembic revision --autogenerate -m "create users and auth_identities"`
Expected: genera un archivo en `alembic/versions/` con `op.create_table('users', ...)` y `op.create_table('auth_identities', ...)`, y la creación del enum `auth_provider`.

- [ ] **Step 5: Revisar la migración generada**

Abrir el archivo nuevo en `alembic/versions/`. Confirmar que:
- `down_revision` apunta a `4f5760921fc1` (la migración de countries).
- crea `users` y `auth_identities`.
- crea el tipo `auth_provider` (o lo referencia con `sa.Enum(..., name='auth_provider')`).
- existe el `UniqueConstraint` sobre (`provider`, `identifier`).

Si todo está, no se edita nada (no hay seed acá).

- [ ] **Step 6: Aplicar a `margin` y verificar**

Run: `alembic upgrade head && psql -d margin -tAc "\dt" | grep -E "users|auth_identities" && psql -d margin -tAc "select enumlabel from pg_enum join pg_type on pg_type.oid=enumtypid where typname='auth_provider';"`
Expected: aparecen `users` y `auth_identities`, y el enum imprime `email`.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/models backend/alembic/versions
git commit -m "feat(backend): modelos users y auth_identities con enum auth_provider"
```

---

## Task 5: Schemas + harness de tests para escritura

**Files:** Create `backend/app/schemas/auth.py`, Modify `backend/tests/conftest.py`

- [ ] **Step 1: `app/schemas/auth.py`**

```python
import uuid

from pydantic import BaseModel, ConfigDict


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    country_code: str
    display_name: str | None


class AuthResponse(BaseModel):
    user: UserRead
    token: str
```

> `email`/`password` van como `str` plano (sin `EmailStr`/`min_length`): la validación de negocio la hace el servicio con los codes del catálogo. Campos faltantes los agarra Pydantic → `validation_failed`.

- [ ] **Step 2: Actualizar `tests/conftest.py` — savepoint + fixture `seed_uy`**

Cambiar la línea de creación de la sesión para permitir que el servicio haga `commit` sin romper el aislamiento de los tests:

Reemplazar:

```python
    session = TestingSessionLocal(bind=connection)
```

por:

```python
    session = TestingSessionLocal(bind=connection, join_transaction_mode="create_savepoint")
```

Y agregar al final del archivo la fixture que siembra el país (los `users` necesitan que exista `UY`):

```python
@pytest.fixture
def seed_uy(db_session):
    from decimal import Decimal

    from app.models.country import Country

    db_session.add(Country(code="UY", name="Uruguay", visible=True, vat_rate=Decimal("22.00")))
    db_session.flush()
```

- [ ] **Step 3: Verificar que la suite sigue verde**

Run: `cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate && pytest -q`
Expected: pasan todos los tests existentes.

- [ ] **Step 4: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/schemas/auth.py backend/tests/conftest.py
git commit -m "feat(backend): schemas de auth y harness para tests con escritura"
```

---

## Task 6: Registro (servicio + endpoint) — TDD

**Files:** Create `backend/app/services/__init__.py`, `backend/app/services/auth_service.py`, `backend/app/routers/auth.py`, `backend/tests/test_auth_register.py`, Modify `backend/app/main.py`

- [ ] **Step 1: Tests que fallan `tests/test_auth_register.py`**

```python
from sqlalchemy import select

from app.models.auth_identity import AuthIdentity


def test_register_creates_user_and_returns_token(client, db_session, seed_uy):
    resp = client.post(
        "/auth/register",
        json={"email": "Juan@Example.com ", "password": "miclave123", "display_name": "Juan"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["country_code"] == "UY"
    assert body["user"]["display_name"] == "Juan"
    assert body["token"]

    identity = db_session.execute(select(AuthIdentity)).scalars().one()
    assert identity.identifier == "juan@example.com"  # normalizado
    assert identity.password_hash != "miclave123"  # hasheado


def test_register_token_contains_user_id(client, seed_uy):
    resp = client.post("/auth/register", json={"email": "a@b.com", "password": "12345678"})
    from app.core.security import decode_access_token

    payload = decode_access_token(resp.json()["token"])
    assert payload["user_id"] == resp.json()["user"]["id"]


def test_register_rejects_invalid_email(client, seed_uy):
    resp = client.post("/auth/register", json={"email": "no-es-email", "password": "12345678"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "email_invalid"
    assert body["field"] == "email"


def test_register_rejects_short_password(client, seed_uy):
    resp = client.post("/auth/register", json={"email": "a@b.com", "password": "corta"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "password_too_short"


def test_register_rejects_duplicate_email(client, seed_uy):
    payload = {"email": "dup@b.com", "password": "12345678"}
    assert client.post("/auth/register", json=payload).status_code == 201
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 409
    assert resp.json()["code"] == "email_already_registered"


def test_register_missing_password_returns_validation_failed(client, seed_uy):
    resp = client.post("/auth/register", json={"email": "a@b.com"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_failed"
    assert "errors" in body
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_auth_register.py -v`
Expected: FALLAN (no existe el endpoint / el servicio).

- [ ] **Step 3: `app/services/__init__.py` vacío + `app/services/auth_service.py`**

```bash
cd /Users/tachone/proyectos/margin/backend && touch app/services/__init__.py
```

```python
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
```

> `login_user` se incluye completo acá (lo usa la Task 7); su endpoint se agrega en esa task.

- [ ] **Step 4: `app/routers/auth.py`**

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.auth import AuthResponse, RegisterRequest, UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user, token = auth_service.register_user(db, data)
    return AuthResponse(user=UserRead.model_validate(user), token=token)
```

- [ ] **Step 5: Montar el router en `app/main.py`**

Reemplazar el contenido por:

```python
from fastapi import FastAPI

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.routers import auth, countries, health

app = FastAPI(title=settings.app_name)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(countries.router)
app.include_router(auth.router)
```

- [ ] **Step 6: Correr y verificar que pasan**

Run: `pytest tests/test_auth_register.py -v`
Expected: PASAN los 6 tests.

- [ ] **Step 7: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/services backend/app/routers/auth.py backend/app/main.py backend/tests/test_auth_register.py
git commit -m "feat(backend): POST /auth/register con servicio y tests"
```

---

## Task 7: Login (endpoint) — TDD

**Files:** Create `backend/tests/test_auth_login.py`, Modify `backend/app/routers/auth.py`

- [ ] **Step 1: Tests que fallan `tests/test_auth_login.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.user import User


def _register(client, email="u@b.com", password="12345678"):
    return client.post("/auth/register", json={"email": email, "password": password})


def test_login_ok(client, seed_uy):
    _register(client)
    resp = client.post("/auth/login", json={"email": "u@b.com", "password": "12345678"})
    assert resp.status_code == 200
    assert resp.json()["token"]
    assert resp.json()["user"]["country_code"] == "UY"


def test_login_wrong_password(client, seed_uy):
    _register(client)
    resp = client.post("/auth/login", json={"email": "u@b.com", "password": "incorrecta"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "credentials_invalid"


def test_login_unknown_email(client, seed_uy):
    resp = client.post("/auth/login", json={"email": "nadie@b.com", "password": "12345678"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "credentials_invalid"


def test_login_soft_deleted_user(client, db_session, seed_uy):
    _register(client)
    user = db_session.execute(select(User)).scalars().one()
    user.deleted_at = datetime.now(timezone.utc)
    db_session.flush()
    resp = client.post("/auth/login", json={"email": "u@b.com", "password": "12345678"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "credentials_invalid"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_auth_login.py -v`
Expected: FALLAN (el endpoint `/auth/login` no existe → 404).

- [ ] **Step 3: Agregar el endpoint de login en `app/routers/auth.py`**

Agregar el import de `LoginRequest` y la ruta. El archivo completo queda:

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user, token = auth_service.register_user(db, data)
    return AuthResponse(user=UserRead.model_validate(user), token=token)


@router.post("/login", response_model=AuthResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user, token = auth_service.login_user(db, data)
    return AuthResponse(user=UserRead.model_validate(user), token=token)
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `pytest tests/test_auth_login.py -v`
Expected: PASAN los 4 tests.

- [ ] **Step 5: Verificar la suite completa**

Run: `pytest -q`
Expected: pasan TODOS (health, countries, security, errors, register, login).

- [ ] **Step 6: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/app/routers/auth.py backend/tests/test_auth_login.py
git commit -m "feat(backend): POST /auth/login con tests"
```

---

## Task 8: Verificación en vivo + CLAUDE.md

**Files:** Modify `backend/CLAUDE.md`

- [ ] **Step 1: Verificar a mano contra la base real**

```bash
cd /Users/tachone/proyectos/margin/backend && source .venv/bin/activate
uvicorn app.main:app --port 8099 >/tmp/uvicorn.log 2>&1 &
UVPID=$!
curl -s --retry 10 --retry-connrefused --retry-delay 1 -X POST http://127.0.0.1:8099/auth/register \
  -H 'Content-Type: application/json' -d '{"email":"demo@margin.uy","password":"12345678","display_name":"Demo"}'
echo ""
curl -s -X POST http://127.0.0.1:8099/auth/login \
  -H 'Content-Type: application/json' -d '{"email":"demo@margin.uy","password":"12345678"}'
kill $UVPID 2>/dev/null
```
Expected: ambos devuelven `{"user":{...,"country_code":"UY",...},"token":"..."}` (register 201, login 200).

- [ ] **Step 2: Limpiar el usuario de prueba de la base `margin`**

Run: `psql -d margin -c "delete from auth_identities; delete from users;"`
Expected: `DELETE 1` en cada una (no dejar datos de prueba en dev).

- [ ] **Step 3: Actualizar `backend/CLAUDE.md`**

Agregar, en la sección "Estructura", estas líneas:

```markdown
- `app/services/` — lógica de negocio (no conoce HTTP; lanza AppError). Ej: `auth_service`.
- `app/core/security.py` — hash de password (bcrypt) + JWT (HS256).
- `app/core/errors.py` — catálogo de error codes + AppError + handlers (formato de error de GLOBAL).
```

Y en "Convenciones", agregar:

```markdown
- Errores: lanzar `AppError(ErrorCode.x)` desde el servicio; nunca `HTTPException`. El formato lo rinden los handlers.
- Endpoints: router finito → servicio. El router no valida reglas de negocio.
```

- [ ] **Step 4: Commit**

```bash
cd /Users/tachone/proyectos/margin
git add backend/CLAUDE.md
git commit -m "docs(backend): CLAUDE.md con capas de services/errors/security"
```

---

## Self-review (writing-plans)

- **Cobertura del spec:** modelos users/auth_identities + enum (T4) ✓; security hash+JWT (T2) ✓; errores catálogo+AppError+handlers (T3) ✓; schemas (T5) ✓; capa de servicio (T6) ✓; register (T6) ✓; login (T7) ✓; validación manual en orden + credentials_invalid único (T6/T7) ✓; country_code sin default, fijado por el servicio (`DEFAULT_COUNTRY_CODE`, T6) ✓; testing por endpoint + token + handlers (T6/T7) ✓. Plan default: diferido (no hay task, correcto).
- **Placeholders:** ninguno; cada paso trae código/comando completo.
- **Consistencia de tipos:** `register_user`/`login_user` devuelven `tuple[User, str]` y el router los consume igual; `AuthResponse{user:UserRead, token}` consistente en schema, router y asserts; `ErrorCode.<name>` usado igual en servicio, handlers y tests; fixture `seed_uy` usada por todos los tests que escriben users.

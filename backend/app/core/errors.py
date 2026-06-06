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

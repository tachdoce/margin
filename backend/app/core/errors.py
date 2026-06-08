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
    not_found = (404, "No encontrado.")
    income_type_invalid = (422, "Tipo de ingreso no válido.")
    currency_not_available = (422, "Esa moneda no está disponible. Elegí otra.")
    description_invalid = (422, "La descripción es obligatoria y debe tener al menos 8 caracteres.")
    amount_invalid = (422, "El monto debe ser mayor a 0.")
    payment_day_invalid = (422, "El día de cobro debe estar entre 1 y 31.")
    recurring_income_requires_payment_day = (422, "Un ingreso recurrente necesita un día de cobro.")
    fixed_term_income_requires_dates = (422, "Un ingreso de duración fija necesita fecha de primer cobro y cantidad de meses.")
    total_months_invalid = (422, "La cantidad de meses debe ser 1 o más.")
    income_form_inconsistent = (422, "Las columnas no corresponden a la forma del ingreso (recurrente o duración fija).")
    field_not_nullable = (422, "Ese campo no puede ser nulo.")
    income_not_deleted = (409, "Este ingreso no está borrado.")
    name_required = (422, "El plan necesita un nombre.")
    dial_amount_invalid = (422, "El monto del dial debe ser mayor o igual a 0.")
    goal_invalid = (422, "El objetivo no es válido.")
    empty_patch = (422, "No hay cambios para aplicar.")
    default_plan_undeletable = (409, "El plan actual no se puede borrar.")
    default_plan_no_movements = (409, "El plan actual no admite movimientos. Creá un plan nuevo para simular escenarios.")
    kind_invalid = (422, "Tipo de movimiento no válido.")
    installments_invalid = (422, "Las cuotas no son válidas.")
    movement_fields_invalid = (422, "Los datos del movimiento no coinciden con su tipo.")
    expense_type_invalid = (422, "Tipo de gasto no válido.")
    priority_level_invalid = (422, "Nivel de prioridad no válido.")
    due_day_invalid = (422, "El día de vencimiento debe estar entre 1 y 31.")
    one_time_expense_inconsistent = (422, "Un gasto con fecha única debe ser no recurrente y sin día de vencimiento.")
    expense_recurring_requires_due_day = (422, "Un gasto recurrente necesita un día de vencimiento.")
    one_time_date_in_past = (422, "La fecha del gasto no puede ser anterior a hoy.")

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

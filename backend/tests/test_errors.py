def test_app_error_carries_status_and_message():
    from app.core.errors import AppError, ErrorCode

    err = AppError(ErrorCode.email_already_registered, field="email")
    assert err.code.status_code == 409
    assert err.code.message == "Ese email ya está registrado."
    assert err.field == "email"

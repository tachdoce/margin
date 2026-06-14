from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config de la app, leída de variables de entorno / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Margin API"
    environment: str = "development"
    # Socket Unix + auth peer (usuario del SO). Sin host = socket por defecto.
    database_url: str = "postgresql+psycopg2:///margin"
    test_database_url: str = "postgresql+psycopg2:///margin_test"
    secret_key: str = "dev-insecure-change-me"
    jwt_expire_days: int = 45
    cors_origins: list[str] = [
        "http://localhost:5173", "http://127.0.0.1:5173",  # /web (banco de pruebas)
        "http://localhost:5174", "http://127.0.0.1:5174",  # web2 (prototipo de producto)
    ]
    bootstrap_version: str = "1"


settings = Settings()

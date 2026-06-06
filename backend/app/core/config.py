from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config de la app, leída de variables de entorno / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Margin API"
    environment: str = "development"
    # Socket Unix + auth peer (usuario del SO). Sin host = socket por defecto.
    database_url: str = "postgresql+psycopg2:///margin"
    test_database_url: str = "postgresql+psycopg2:///margin_test"


settings = Settings()

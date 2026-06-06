from fastapi import FastAPI

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.routers import countries, health

app = FastAPI(title=settings.app_name)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(countries.router)

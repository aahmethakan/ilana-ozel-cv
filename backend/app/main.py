from fastapi import FastAPI

from app.api.router import api_v1_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.core.exception_handlers import unexpected_exception_handler

settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_exception_handler(Exception, unexpected_exception_handler)
app.include_router(health_router)
app.include_router(api_v1_router)

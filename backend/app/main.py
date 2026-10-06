import asyncio
import logging
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_v1_router
from app.api.routes.health import router as health_router
from app.api.routes.ui import router as ui_router
from app.core.config import get_settings
from app.core.exception_handlers import (
    api_http_exception_handler,
    request_validation_exception_handler,
    unexpected_exception_handler,
)
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version)
logger = logging.getLogger("ilana.request")
_expensive_operations = asyncio.Semaphore(settings.expensive_operation_concurrency)
_EXPENSIVE_PATHS = frozenset({"/api/v1/cv/analyze", "/api/v1/cv/generate/review/rewrite", "/api/v1/cv/generate/cover-letter/rewrite"})


@app.middleware("http")
async def production_safety_headers_and_capacity(request, call_next):
    request_id = uuid4().hex
    started = time.perf_counter()
    acquired = False
    if request.url.path in _EXPENSIVE_PATHS:
        if _expensive_operations.locked():
            response = JSONResponse(status_code=429, content={"error": {"code": "operation_capacity_exceeded", "message": "The service is busy. Please try again shortly."}})
            response.headers["X-Request-ID"] = request_id
            return response
        await _expensive_operations.acquire()
        acquired = True
    try:
        response = await call_next(request)
    finally:
        if acquired:
            _expensive_operations.release()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    response.headers["X-Request-ID"] = request_id
    logger.info("request_complete request_id=%s method=%s path=%s status=%s duration_ms=%d", request_id, request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
    return response
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.add_exception_handler(Exception, unexpected_exception_handler)
app.add_exception_handler(HTTPException, api_http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(health_router)
app.include_router(ui_router)
app.include_router(api_v1_router)

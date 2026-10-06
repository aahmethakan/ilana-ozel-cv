from fastapi import APIRouter

from app.core.errors import ErrorResponse

from app.api.routes.health import router as health_router
from app.api.routes.cv import router as cv_router
from app.api.routes.jobs import router as jobs_router

api_v1_router = APIRouter(
    prefix="/api/v1",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request."},
        404: {"model": ErrorResponse, "description": "Required session or state was not found."},
        409: {"model": ErrorResponse, "description": "The requested state is stale."},
        415: {"model": ErrorResponse, "description": "Unsupported media type."},
        422: {"model": ErrorResponse, "description": "The request could not be processed safely."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
api_v1_router.include_router(health_router)
api_v1_router.include_router(cv_router)
api_v1_router.include_router(jobs_router)

from fastapi import APIRouter, status
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from app.api.routes.cv import session_store
from app.core.config import get_settings

router = APIRouter()


class PublicReleaseInfo(BaseModel):
    """Public, non-sensitive release information for the legal footer."""

    project_name: str
    version: str
    copyright_holder: str | None
    source_code_url: str | None


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness_check() -> JSONResponse:
    try:
        assert session_store.persistence is not None
        session_store.persistence.load("readiness-probe")
    except Exception:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "not_ready"})
    return JSONResponse(content={"status": "ready"})


@router.get("/about", response_model=PublicReleaseInfo)
def public_release_info() -> PublicReleaseInfo:
    settings = get_settings()
    return PublicReleaseInfo(
        project_name="Ilana Ozel CV",
        version=settings.app_version,
        copyright_holder=settings.copyright_holder,
        source_code_url=settings.source_code_url,
    )

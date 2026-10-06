from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["development-ui"])
_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


@router.get("/", include_in_schema=False)
def development_ui() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")


@router.get("/license", include_in_schema=False)
def project_license() -> FileResponse:
    return FileResponse(_PROJECT_ROOT / "LICENSE", media_type="text/plain; charset=utf-8")


@router.get("/third-party-notices", include_in_schema=False)
def third_party_notices() -> FileResponse:
    return FileResponse(_PROJECT_ROOT / "THIRD_PARTY_NOTICES.md", media_type="text/markdown; charset=utf-8")

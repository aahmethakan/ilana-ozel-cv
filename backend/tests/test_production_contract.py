import asyncio

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app


def test_production_configuration_requires_private_explicit_contract() -> None:
    valid = Settings(
        environment="production",
        session_db_path="C:/runtime/sessions.sqlite3",
        allowed_hosts=("cv.example.test",),
        cors_allowed_origins=("https://cv.example.test",),
        copyright_holder="Example Owner",
        source_code_url="https://source.example.test/ilana-ozel-cv/tree/v0.1.0-rc.1",
    )
    assert valid.environment == "production"
    for values in (
        {"session_db_path": "relative.sqlite3"},
        {"allowed_hosts": ()},
        {"allowed_hosts": ("*",)},
        {"cors_allowed_origins": ("*",)},
        {"copyright_holder": None},
        {"source_code_url": None},
    ):
        with pytest.raises(ValidationError):
            Settings(**{
                "environment": "production",
                "session_db_path": "C:/runtime/sessions.sqlite3",
                "allowed_hosts": ("cv.example.test",),
                "cors_allowed_origins": ("https://cv.example.test",),
                "copyright_holder": "Example Owner",
                "source_code_url": "https://source.example.test/ilana-ozel-cv/tree/v0.1.0-rc.1",
                **values,
            })


@pytest.mark.parametrize("source_code_url", ("javascript:alert(1)", "file:///private/source", "https://user:secret@example.test/source", "https://example.test/source#fragment"))
def test_source_code_url_rejects_unsafe_or_non_corresponding_shapes(source_code_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(source_code_url=source_code_url)


def test_settings_reject_invalid_resource_values() -> None:
    for values in ({"session_ttl_hours": 0}, {"pdf_max_bytes": 0}, {"pdf_max_pages": 0}, {"expensive_operation_concurrency": 0}):
        with pytest.raises(ValidationError):
            Settings(**values)


async def _get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


def test_ready_and_request_security_contract() -> None:
    first, second = asyncio.run(_get("/api/v1/ready")), asyncio.run(_get("/api/v1/health"))
    assert first.status_code == 200 and first.json() == {"status": "ready"}
    assert second.status_code == 200
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    for response in (first, second):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "strict-transport-security" not in response.headers

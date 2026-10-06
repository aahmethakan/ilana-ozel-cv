import asyncio

import httpx

from app.core.config import get_settings
from app.main import app


async def request(path: str, *, raise_app_exceptions: bool = True) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_root_health_check_returns_ok() -> None:
    response = asyncio.run(request("/health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_versioned_health_check_returns_ok() -> None:
    response = asyncio.run(request("/api/v1/health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_application_metadata_comes_from_settings() -> None:
    settings = get_settings()

    assert settings.app_name == "Ilana Ozel CV API"
    assert settings.app_version == "0.1.0-rc.1"
    assert settings.environment == "development"
    assert settings.debug is False
    assert app.title == settings.app_name
    assert app.version == settings.app_version


def test_public_release_info_is_safe_and_does_not_claim_an_unconfigured_source() -> None:
    response = asyncio.run(request("/api/v1/about"))

    assert response.status_code == 200
    assert response.json() == {
        "project_name": "Ilana Ozel CV",
        "version": "0.1.0-rc.1",
        "copyright_holder": None,
        "source_code_url": None,
    }


def test_legal_documents_are_served_without_runtime_data() -> None:
    license_response = asyncio.run(request("/license"))
    notices_response = asyncio.run(request("/third-party-notices"))

    assert license_response.status_code == notices_response.status_code == 200
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_response.text
    assert "PyMuPDF" in notices_response.text
    assert "session_id" not in notices_response.text


def test_unexpected_errors_return_safe_json() -> None:
    route_count = len(app.router.routes)

    async def raise_unexpected_error() -> None:
        raise RuntimeError("internal test exception detail")

    app.add_api_route("/_test/unexpected-error", raise_unexpected_error)
    try:
        response = asyncio.run(request("/_test/unexpected-error", raise_app_exceptions=False))
    finally:
        del app.router.routes[route_count:]

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred.",
        }
    }
    assert "internal test exception detail" not in response.text

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.routes import health as health_routes
from app.core.config import Settings
from app.services.analysis_session import AnalysisSessionStore
from app.services.analysis_session import service as session_service


PROJECT_ROOT = Path(__file__).parents[2]


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "session_db_path": "C:/runtime/sessions.sqlite3",
        "allowed_hosts": ("cv.example.test",),
        "cors_allowed_origins": ("https://cv.example.test",),
        "copyright_holder": "AHA",
        "source_code_url": "https://github.com/aahmethakan/ilana-ozel-cv/tree/v0.1.0-rc.2",
    }
    values.update(overrides)
    return Settings(**values)


def test_durable_production_mode_remains_the_default_and_requires_an_absolute_database_path() -> None:
    assert _production_settings().session_persistence_mode == "durable"
    with pytest.raises(ValidationError):
        _production_settings(session_db_path="relative.sqlite3")


def test_ephemeral_production_mode_explicitly_allows_no_durable_database_path() -> None:
    settings = _production_settings(session_persistence_mode="ephemeral", session_db_path="relative.sqlite3")

    assert settings.session_persistence_mode == "ephemeral"


@pytest.mark.parametrize("overrides", (
    {"allowed_hosts": ("*",)},
    {"cors_allowed_origins": ("*",)},
    {"source_code_url": None},
))
def test_ephemeral_production_mode_retains_host_cors_and_source_contracts(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _production_settings(session_persistence_mode="ephemeral", **overrides)


def test_ephemeral_store_does_not_construct_or_use_sqlite_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_service, "get_settings", lambda: Settings(session_persistence_mode="ephemeral"))

    class UnexpectedSQLitePersistence:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("ephemeral mode must not initialize SQLite persistence")

    monkeypatch.setattr(session_service, "SQLiteSessionPersistence", UnexpectedSQLitePersistence)
    store = AnalysisSessionStore()

    assert store.persistence is None
    assert store.get("unknown") is None
    store.delete("unknown")


def test_ready_accepts_explicit_ephemeral_mode_without_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_routes, "get_settings", lambda: _production_settings(session_persistence_mode="ephemeral", session_db_path="relative.sqlite3"))
    monkeypatch.setattr(health_routes.session_store, "persistence", None)

    response = health_routes.readiness_check()

    assert response.status_code == 200
    assert json.loads(response.body) == {"status": "ready"}


def test_durable_ready_still_requires_sqlite_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_routes, "get_settings", lambda: Settings())
    monkeypatch.setattr(health_routes.session_store, "persistence", None)

    response = health_routes.readiness_check()

    assert response.status_code == 503
    assert json.loads(response.body) == {"status": "not_ready"}


def test_render_free_documentation_pins_runtime_and_declares_ephemeral_contract() -> None:
    deployment = (PROJECT_ROOT / "backend" / "DEPLOYMENT.md").read_text(encoding="utf-8")

    assert (PROJECT_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13.15"
    assert "ILANA_SESSION_PERSISTENCE_MODE=ephemeral" in deployment
    assert "python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1" in deployment
    assert "https://github.com/aahmethakan/ilana-ozel-cv/tree/v0.1.0-rc.2" in deployment

"""Versioned, minimal SQLite persistence for analysis-session canonical state."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PersistedAnalysisSessionV1(BaseModel):
    """Only canonical/user-confirmed recovery state; no PDFs or generated output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    context_revision: int = Field(ge=0)
    profile: dict[str, Any]
    # The source PDF is deliberately never persisted.  Retaining the
    # deterministic analysis result prevents recovery from silently replacing
    # document-based structure/ATS scores with an incomplete document=None
    # recalculation after a server restart.
    quality: dict[str, Any] | None = None
    unresolved_evidence: list[dict[str, Any]] = Field(default_factory=list)
    readiness_rejected_evidence_ids: list[str] = Field(default_factory=list)
    coach_candidates: dict[str, dict[str, Any]] = Field(default_factory=dict)
    coach_resolution_status: dict[str, str] = Field(default_factory=dict)
    resolved_candidate_ids: list[str] = Field(default_factory=list)
    continuation_candidates: dict[str, dict[str, Any]] = Field(default_factory=dict)
    continuation_resolutions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    job_analysis: dict[str, Any] | None = None


class SQLiteSessionPersistence:
    """Atomic, lazy-loaded session snapshots stored outside the source tree."""

    def __init__(self, path: Path, *, ttl_hours: int = 24) -> None:
        self.path = path
        self.ttl = timedelta(hours=ttl_hours)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS analysis_sessions (session_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS analysis_sessions_expiry ON analysis_sessions(expires_at)")
            self._cleanup(connection)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _cleanup(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM analysis_sessions WHERE expires_at <= ?", (self._now().isoformat(),))

    def save(self, session_id: str, snapshot: PersistedAnalysisSessionV1) -> None:
        now = self._now()
        expires = now + self.ttl
        payload = snapshot.model_dump_json()
        with closing(self._connect()) as connection, connection:
            self._cleanup(connection)
            connection.execute(
                "INSERT INTO analysis_sessions(session_id, schema_version, payload, created_at, updated_at, expires_at) VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET schema_version=excluded.schema_version, payload=excluded.payload, updated_at=excluded.updated_at, expires_at=excluded.expires_at",
                (session_id, snapshot.schema_version, payload, now.isoformat(), now.isoformat(), expires.isoformat()),
            )

    def load(self, session_id: str) -> PersistedAnalysisSessionV1 | None:
        with closing(self._connect()) as connection, connection:
            self._cleanup(connection)
            row = connection.execute("SELECT schema_version, payload FROM analysis_sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is None or row[0] != 1:
                return None
            try:
                return PersistedAnalysisSessionV1.model_validate(json.loads(row[1]))
            except (ValueError, TypeError):
                connection.execute("DELETE FROM analysis_sessions WHERE session_id = ?", (session_id,))
                return None

    def delete(self, session_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM analysis_sessions WHERE session_id = ?", (session_id,))

    def cleanup(self) -> None:
        with self._connect() as connection:
            self._cleanup(connection)

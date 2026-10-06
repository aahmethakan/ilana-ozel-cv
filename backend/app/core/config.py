import os
import tempfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ilana Ozel CV API"
    app_version: str = "0.1.0-rc.1"
    environment: str = "development"
    debug: bool = False
    copyright_holder: str | None = None
    source_code_url: str | None = None
    cors_allowed_origins: tuple[str, ...] = ("http://localhost:5173",)
    # An explicit ILANA_SESSION_DB_PATH wins.  The default is the OS temp
    # runtime area, never the repository or an uploaded-document directory.
    session_db_path: Path = Path(os.environ.get("ILANA_SESSION_DB_PATH", Path(tempfile.gettempdir()) / "ilana-ozel-cv" / "sessions.sqlite3"))
    session_ttl_hours: int = 24
    pdf_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=50 * 1024 * 1024)
    pdf_max_pages: int = Field(default=50, ge=1, le=500)
    expensive_operation_concurrency: int = Field(default=2, ge=1, le=8)
    allowed_hosts: tuple[str, ...] = ("*",)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ILANA_",
        extra="ignore",
    )

    @field_validator("copyright_holder")
    @classmethod
    def copyright_holder_is_nonblank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("copyright holder must be non-blank when configured")
        return value

    @field_validator("source_code_url")
    @classmethod
    def source_code_url_is_safe_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("source code URL must be an absolute HTTP(S) URL without credentials or a fragment")
        return value

    @model_validator(mode="after")
    def production_contract(self) -> "Settings":
        if self.environment not in {"development", "production"}:
            raise ValueError("environment must be development or production")
        if self.session_ttl_hours < 1 or self.session_ttl_hours > 168:
            raise ValueError("session TTL must be between 1 and 168 hours")
        if self.environment == "production":
            if not self.session_db_path.is_absolute():
                raise ValueError("production session database path must be absolute")
            if not self.allowed_hosts or "*" in self.allowed_hosts:
                raise ValueError("production allowed hosts must be explicit")
            if any(origin == "*" for origin in self.cors_allowed_origins):
                raise ValueError("production CORS origins cannot use wildcard")
            if self.copyright_holder is None:
                raise ValueError("production requires an explicit copyright holder")
            if self.source_code_url is None:
                raise ValueError("production requires an exact corresponding source code URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

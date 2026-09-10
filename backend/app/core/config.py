from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ilana Ozel CV API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ILANA_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

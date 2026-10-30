from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./margin.db"

    # Answers. Unset: offline mode, which quotes the best passages instead of writing an answer.
    anthropic_api_key: str | None = None
    margin_model: str = "claude-opus-5-5"
    margin_effort: str = "medium"

    # Embeddings for semantic search. Unset: keyword search only.
    voyage_api_key: str | None = None
    voyage_model: str = "voyage-3.5"
    embedding_dim: int = 1024

    # Login for the web app and API. Unset password: a random one is generated and logged.
    margin_user: str = "reader"
    margin_password: str | None = None

    seed_library: bool = True
    max_upload_mb: int = 10
    top_k: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()

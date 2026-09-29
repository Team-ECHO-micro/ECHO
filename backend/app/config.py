from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = ""
    hindsight_api_key: str = ""
    virtual_now: str = "2026-01-01T09:00:00+00:00"

    groq_primary_model: str = "openai/gpt-oss-20b"
    groq_fallback_model: str = "qwen/qwen3-32b"
    hindsight_base_url: str = "https://api.hindsight.vectorize.io"
    hindsight_timeout_seconds: float = 8.0


settings = Settings()

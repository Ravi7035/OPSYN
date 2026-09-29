"""Centralized application configuration.

All secrets come from environment variables (or a local `.env` file).
Only non-sensitive values carry defaults.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the SRE backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="sre-incident-backend")
    environment: str = Field(default="development")

    hindsight_api_key: str = Field(default="", alias="HINDSIGHT_API_KEY")
    hindsight_base_url: str = Field(
        default="https://api.hindsight.vectorize.io",
        alias="HINDSIGHT_BASE_URL",
    )
    hindsight_bank_id: str = Field(
        default="sre-organizational-memory",
        alias="HINDSIGHT_BANK_ID",
    )

    agent_max_investigation_steps: int = Field(default=10)
    agent_max_actions: int = Field(default=3)

    incident_store_path: str = Field(
        default="data/incidents.json",
        alias="INCIDENT_STORE_PATH",
    )

    # Public URL(s) of the deployed frontend, e.g.
    # FRONTEND_URL=https://opsyn.vercel.app
    # Comma-separated if more than one. Empty = localhost only (local dev).
    # Browser requests from any other origin are rejected; never use "*".
    frontend_url: str = Field(default="", alias="FRONTEND_URL")

    reasoning_model: str = Field(default="deterministic", alias="REASONING_MODEL")

    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(
        default="openai/gpt-oss-120b",
        alias="GROQ_MODEL",
    )
    groq_reasoning_effort: str = Field(
        default="high",
        alias="GROQ_REASONING_EFFORT",
    )
    groq_timeout_s: float = Field(default=60.0, alias="GROQ_TIMEOUT_S")
    groq_max_retries: int = Field(default=2, alias="GROQ_MAX_RETRIES")
    groq_max_completion_tokens: int = Field(
        default=4096, alias="GROQ_MAX_COMPLETION_TOKENS"
    )

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(
        default="gemini-3.5-flash",
        alias="GEMINI_MODEL",
    )
    gemini_timeout_s: float = Field(default=60.0, alias="GEMINI_TIMEOUT_S")
    gemini_max_retries: int = Field(default=2, alias="GEMINI_MAX_RETRIES")
    gemini_max_output_tokens: int = Field(
        default=4096, alias="GEMINI_MAX_OUTPUT_TOKENS"
    )

    @property
    def is_hindsight_configured(self) -> bool:
        return bool(self.hindsight_api_key.strip())

    @property
    def is_groq_configured(self) -> bool:
        return bool(self.groq_api_key.strip())

    @property
    def is_gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()

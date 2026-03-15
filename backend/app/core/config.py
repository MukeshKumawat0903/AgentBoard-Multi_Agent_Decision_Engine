"""
Application configuration via pydantic-settings.

Loads environment variables from .env file and provides
a singleton Settings instance for the entire application.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AgentBoard application settings loaded from environment variables."""

    # --- GROQ LLM Configuration ---
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # --- Debate Engine Configuration ---
    MAX_DEBATE_ROUNDS: int = 4
    CONSENSUS_THRESHOLD: float = 0.75

    # --- Application Configuration ---
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- Persistence ---
    DATABASE_URL: str = "agentboard.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


# Singleton instance – import this everywhere
settings = Settings()

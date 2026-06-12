"""
Application configuration via pydantic-settings.

Loads environment variables from .env file and provides
a singleton Settings instance for the entire application.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AgentBoard application settings loaded from environment variables."""

    # --- Application Environment ---
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_VERSION: str = "2.0.0"

    # --- GROQ LLM Configuration (primary provider) ---
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # --- Multi-Provider LLM Support (Phase 1) ---
    # Switch active provider via LLM_PROVIDER env var.
    LLM_PROVIDER: Literal["groq", "openai", "anthropic", "gemini"] = "groq"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5.5"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-4-8"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"

    # --- Debate Engine Configuration ---
    # Orchestrator-level fallbacks used only when DebateGraph is driven directly
    # without going through resolve_debate_config's mode presets (see
    # debate_graph.py / nodes.py). Aligned with the "standard" mode preset so
    # the two don't silently disagree.
    MAX_DEBATE_ROUNDS: int = 4
    CONSENSUS_THRESHOLD: float = 0.75

    # Per-phase agent timeouts (seconds). Tunable so slower providers
    # (OpenAI/Anthropic) or agents that run a web search plus an LLM call in the
    # same window are not silently dropped. Tool-using agents get the multiplier.
    AGENT_PROPOSAL_TIMEOUT: float = 45.0
    AGENT_CRITIQUE_TIMEOUT: float = 45.0
    AGENT_REVISION_TIMEOUT: float = 45.0
    AGENT_TOOL_TIMEOUT_MULTIPLIER: float = 1.5

    # Debate-tuning constants.
    # Drift below this between consecutive rounds means agents have stopped moving.
    DRIFT_EARLY_STOP_THRESHOLD: float = 0.05
    # An agent whose final confidence is this far below the group mean is a dissenter.
    MINORITY_REPORT_BAND: float = 0.20
    # When the moderator says "stop" and every agent is at least this confident, stop.
    ALL_CONFIDENT_THRESHOLD: float = 0.9
    # Max tool invocations an agent may make per proposal/revision call.
    MAX_TOOL_CALLS_PER_ROUND: int = 3

    # --- Application Configuration ---
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- Security ---
    SECRET_KEY: str = "change-me-in-production-use-a-32-char-secret"
    RATE_LIMIT_PER_MINUTE: int = 30

    # --- Agent Registry ---
    # Comma-separated list of agent names that are enabled by default.
    # Override via ENABLED_AGENTS env var to enable/disable agents at runtime.
    ENABLED_AGENTS: str = "Analyst,Risk,Strategy,Ethics,Moderator"

    # --- Persistence ---
    DATABASE_URL: str = "agentboard.db"
    CHECKPOINT_DATABASE_URL: str = "agentboard_checkpoints.db"
    DEBATE_TTL_DAYS: int = 90  # Debates older than this are removed at startup

    # --- LangSmith Observability (Phase 5) ---
    # Set LANGSMITH_TRACING=true in .env to enable full LLM call tracing.
    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "agentboard"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"

    # --- Semantic Consensus (Phase 4) ---
    # Requires sentence-transformers installed.
    SEMANTIC_CONSENSUS_ENABLED: bool = False
    SEMANTIC_MODEL: str = "all-MiniLM-L6-v2"
    # Weight of semantic score vs confidence proxy (0.0 = all confidence, 1.0 = all semantic).
    SEMANTIC_CONSENSUS_WEIGHT: float = 0.5

    # --- Phase 3: Knowledge Base RAG ---
    KNOWLEDGE_BASE_DIR: str = "knowledge_base"
    KB_CHUNK_SIZE: int = 1000
    KB_CHUNK_OVERLAP: int = 200
    KB_SIMILARITY_THRESHOLD: float = 0.30
    KB_TOP_K: int = 5
    KB_EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    KB_MAX_FILE_MB: int = 10

    # --- Phase 4: Human-in-the-Loop ---
    # Set False to disable HITL even when supervised mode is requested.
    HITL_ENABLED: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# Singleton instance – import this everywhere
settings = Settings()  # type: ignore[call-arg]

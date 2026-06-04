"""
Agent Registry for AgentBoard.

Provides a central catalog of available agents with their configs,
enabling dynamic agent discovery, per-agent LLM overrides, and
runtime enable/disable without code changes.

Usage::

    from app.agents.registry import registry

    # List all enabled agents
    names = registry.enabled_agents()

    # Get a specific agent instance
    agent = registry.get("Analyst", llm_client=client)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Type, cast

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.agents.base_agent import BaseAgent
    from app.services.llm_client import LangChainProvider

logger = logging.getLogger("agentboard.agents.registry")


# ---------------------------------------------------------------------------
# AgentConfig – configuration model for a single agent
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    """Per-agent configuration stored in the registry."""

    name: str = Field(description="Canonical agent name (e.g. 'Analyst').")
    role: str = Field(description="Short human-readable role description.")
    icon: str = Field(default="🤖", description="Emoji icon used in UI.")
    system_prompt: str = Field(description="Full system prompt for this agent.")
    enabled: bool = Field(default=True, description="Whether the agent participates in debates.")
    model_provider: str | None = Field(
        default=None,
        description="Override LLM provider for this agent (e.g. 'openai'). None = use global.",
    )
    model_name: str | None = Field(
        default=None,
        description="Override model name for this agent. None = use global.",
    )
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_retries: int = Field(default=2, ge=0)
    allowed_tools: list[str] = Field(default_factory=list)

    model_config = {
        "protected_namespaces": (),
    }


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------

class AgentRegistry:
    """
    Central catalog for all debate agents.

    Agents are registered with their config and class at startup.
    At runtime, ``get()`` instantiates fresh agent objects on demand
    using the stored class + config, injecting any per-agent LLM overrides.
    """

    def __init__(self) -> None:
        self._configs: dict[str, AgentConfig] = {}
        self._classes: dict[str, Type[BaseAgent]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        agent_class: Type[BaseAgent],
        config: AgentConfig,
    ) -> None:
        """Register an agent class together with its config.

        Validates that every name in ``config.allowed_tools`` exists in
        ``TOOL_REGISTRY``.  Raises ``ValueError`` for unknown tool names.
        """
        if config.allowed_tools:
            from app.agents.tools import TOOL_REGISTRY
            unknown_tools = [t for t in config.allowed_tools if t not in TOOL_REGISTRY]
            if unknown_tools:
                raise ValueError(
                    f"Agent '{config.name}' references unknown tool(s): {unknown_tools}. "
                    f"Available tools: {sorted(TOOL_REGISTRY)}"
                )
        self._configs[config.name] = config
        self._classes[config.name] = agent_class
        logger.debug("agent_registered", extra={"name": config.name, "enabled": config.enabled})

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, name: str, llm_client: LangChainProvider) -> BaseAgent:
        """
        Instantiate and return an agent by name.

        If the agent has a model override, a new ``LangChainProvider``
        is built for that agent; otherwise the shared client is used.
        """
        if name not in self._classes:
            raise KeyError(f"Agent '{name}' is not registered.")

        config = self._configs[name]
        effective_client = self._resolve_client(config, llm_client)

        agent_class = cast(Any, self._classes[name])
        instance: BaseAgent = agent_class(llm_client=effective_client)
        instance.allowed_tools = list(config.allowed_tools)
        # B7 Fix: wire per-agent temperature and retry budget so AgentConfig values
        # actually reach the LLM call instead of being silently ignored.
        instance.temperature = config.temperature
        instance.max_retries = config.max_retries
        logger.debug(
            "agent_instantiated",
            extra={
                "name": name,
                "provider": config.model_provider or "global",
                "model": config.model_name or "global",
            },
        )
        return instance

    def _resolve_client(
        self,
        config: AgentConfig,
        default_client: LangChainProvider,
    ) -> LangChainProvider:
        """Return a per-agent LangChainProvider when overrides are configured."""
        if config.model_provider is None and config.model_name is None:
            return default_client

        # Import lazily to avoid circular imports at module load time
        from app.services.llm_client import LangChainProvider as LC
        from app.core.config import settings

        provider = config.model_provider or default_client.provider
        model = config.model_name or default_client.model

        api_key_map: dict[str, str] = {
            "groq": settings.GROQ_API_KEY,
            "openai": settings.OPENAI_API_KEY,
            "anthropic": settings.ANTHROPIC_API_KEY,
        }
        api_key = api_key_map.get(provider, "")
        if not api_key:
            raise ValueError(
                f"Agent '{config.name}' requests provider '{provider}' but no API key "
                f"is configured for it.  Set the corresponding *_API_KEY environment variable."
            )

        return LC(provider=provider, api_key=api_key, model=model)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def is_registered(self, name: str) -> bool:
        return name in self._configs

    def list_agents(self) -> list[AgentConfig]:
        """Return configs for all registered agents (enabled and disabled)."""
        return list(self._configs.values())

    def enabled_agents(self) -> list[str]:
        """Return names of all enabled registered agents."""
        return [name for name, cfg in self._configs.items() if cfg.enabled]

    def get_config(self, name: str) -> AgentConfig:
        if name not in self._configs:
            raise KeyError(f"Agent '{name}' is not registered.")
        return self._configs[name]


# Module-level singleton used throughout the application
registry = AgentRegistry()

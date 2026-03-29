"""
Safe tool implementations for agent-controlled tool use.

Each tool is a LangChain ``BaseTool`` subclass and registered in
``TOOL_REGISTRY``.  Only tools whose names appear in an agent's
``AgentConfig.allowed_tools`` list are exposed to that agent.

Tools are deliberately conservative – no shell execution, no file writes,
no arbitrary network calls.  All heavy computation goes through ``numexpr``
(not Python ``eval``).

Usage::

    from app.agents.tools import TOOL_REGISTRY

    # Get a specific tool
    tool = TOOL_REGISTRY["calculator"]
    result = tool.run("2 ** 10 + 1")   # → "1025"
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger("agentboard.tools")


# ---------------------------------------------------------------------------
# Helper: safe numexpr calculator
# ---------------------------------------------------------------------------

def _safe_calc(expression: str) -> str:
    """Evaluate a safe arithmetic expression using numexpr."""
    try:
        import numexpr  # type: ignore[import-untyped]
    except ImportError:
        return "Error: calculator unavailable — install numexpr (pip install numexpr)."
    try:
        # Restrict to safe characters to prevent injection
        allowed = set("0123456789+-*/()., eE_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ^%")
        if not all(c in allowed for c in expression):
            return "Error: expression contains unsafe characters"
        result = numexpr.evaluate(expression.replace("^", "**"))
        return str(result.item() if hasattr(result, "item") else result)
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Tool implementations (LangChain BaseTool subclasses)
# ---------------------------------------------------------------------------

class WebSearchTool(BaseTool):
    """DuckDuckGo search via langchain-community.  Returns top-2 KB of snippets."""

    name: str = "web_search"
    description: str = "Search the web for current information. Input: a search query string."

    def _run(self, query: str, **kwargs: Any) -> str:
        try:
            from langchain_community.tools import DuckDuckGoSearchRun  # type: ignore[import-untyped]
            search = DuckDuckGoSearchRun()
            return search.run(query)[:2000]  # cap at 2 KB
        except ImportError:
            return "web_search unavailable: langchain-community DuckDuckGoSearchRun not installed."
        except Exception as exc:
            logger.warning("web_search_failed", extra={"query": query, "error": str(exc)})
            return f"Search failed: {exc}"

    async def _arun(self, query: str, **kwargs: Any) -> str:
        return self._run(query)


class CalculatorTool(BaseTool):
    """Safe arithmetic evaluator using numexpr."""

    name: str = "calculator"
    description: str = (
        "Evaluate arithmetic expressions. "
        "Supports +, -, *, /, **, %. "
        "Input: a mathematical expression string."
    )

    def _run(self, expression: str, **kwargs: Any) -> str:
        return _safe_calc(expression.strip())

    async def _arun(self, expression: str, **kwargs: Any) -> str:
        return self._run(expression)


class GetCurrentDateTool(BaseTool):
    """Returns the current date and day name in ISO format."""

    name: str = "get_current_date"
    description: str = "Returns the current UTC date and day of the week."

    def _run(self, tool_input: str = "", **kwargs: Any) -> str:
        now = datetime.now(timezone.utc)
        return f"{now.strftime('%Y-%m-%d')} ({now.strftime('%A')})"

    async def _arun(self, tool_input: str = "", **kwargs: Any) -> str:
        return self._run(tool_input)


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

web_search_tool = WebSearchTool()
calculator_tool = CalculatorTool()
get_current_date_tool = GetCurrentDateTool()

TOOL_REGISTRY: dict[str, BaseTool] = {
    "web_search": web_search_tool,
    "calculator": calculator_tool,
    "get_current_date": get_current_date_tool,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    name: tool.description
    for name, tool in TOOL_REGISTRY.items()
}

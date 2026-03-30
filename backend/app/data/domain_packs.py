"""
Domain Agent Packs for AgentBoard.

Pre-configured agent subsets tailored to specific problem domains.
Each pack selects a subset of the registered agents and may include
domain-specific agent variants.

Usage::

    from app.data.domain_packs import DOMAIN_PACKS, DOMAIN_PACKS_BY_ID

    pack = DOMAIN_PACKS_BY_ID["finance"]
    agents_to_use = pack.agents   # Use this to filter the agent registry
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class DomainPack(BaseModel):
    """Configuration for a domain-specialised agent pack."""

    id: str = Field(description="Unique identifier (e.g. 'finance').")
    name: str = Field(description="Human-readable display name.")
    description: str = Field(description="Short description of the domain focus.")
    icon: str = Field(default="📦", description="Emoji icon.")
    agents: list[str] = Field(description="Ordered list of agent names in this pack.")
    paired_template_categories: list[str] = Field(
        default_factory=list,
        description="Template categories that pair well with this domain pack.",
    )
    domain_focus: str = Field(
        default="",
        description="Short phrase injected into system prompts when this pack is active.",
    )


# ---------------------------------------------------------------------------
# Built-in packs
# ---------------------------------------------------------------------------

DOMAIN_PACKS: list[DomainPack] = [
    DomainPack(
        id="finance",
        name="Finance & Investment",
        description=(
            "Focused on financial analysis, investment risk, regulatory compliance, "
            "and ethical capital allocation.  Includes a dedicated Financial Ethics agent."
        ),
        icon="💰",
        agents=["Analyst", "Risk", "Strategy", "FinancialEthics", "Moderator"],
        paired_template_categories=["Finance", "Business"],
        domain_focus="financial analysis, investment risk, and regulatory compliance",
    ),
    DomainPack(
        id="engineering",
        name="Engineering & Technology",
        description=(
            "Optimised for technology decisions, architecture choices, and security risk.  "
            "Includes a Security agent focused on vulnerability and operational risk."
        ),
        icon="⚙️",
        agents=["Analyst", "Risk", "Strategy", "Security", "Moderator"],
        paired_template_categories=["Technology"],
        domain_focus="software engineering, architecture, and security risk",
    ),
    DomainPack(
        id="legal",
        name="Legal & Compliance",
        description=(
            "Suited for legal analysis, regulatory review, and compliance risk.  "
            "Includes a Compliance agent with regulatory focus."
        ),
        icon="⚖️",
        agents=["Analyst", "Risk", "Ethics", "Compliance", "Moderator"],
        paired_template_categories=["Business", "Strategy"],
        domain_focus="legal risk, regulatory compliance, and ethical obligations",
    ),
    DomainPack(
        id="healthcare",
        name="Healthcare & Life Sciences",
        description=(
            "Designed for healthcare decisions, clinical risk, and patient safety evaluation.  "
            "Includes a Patient Safety agent."
        ),
        icon="🏥",
        agents=["Analyst", "Risk", "Ethics", "PatientSafety", "Moderator"],
        paired_template_categories=["Strategy"],
        domain_focus="clinical risk, patient safety, and healthcare ethics",
    ),
]

DOMAIN_PACKS_BY_ID: dict[str, DomainPack] = {pack.id: pack for pack in DOMAIN_PACKS}

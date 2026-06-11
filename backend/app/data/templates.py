"""
Built-in debate templates.

Each template provides a starting query and recommended settings for a
well-known decision-making scenario.  Templates are exposed via
``GET /templates`` so the frontend can display a searchable picker.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TemplateCategory = Literal[
    "Business",
    "Technology",
    "Strategy",
    "Personal",
    "Finance",
]


class DebateTemplate(BaseModel):
    """A pre-built debate scenario shipped with AgentBoard."""

    id: str = Field(description="URL-safe slug identifier.")
    title: str = Field(description="Short display title.")
    category: TemplateCategory = Field(description="Domain category for grouping in the UI.")
    icon: str = Field(description="Emoji representing the category.")
    query: str = Field(description="Full, ready-to-use query text pre-filling the debate input.")
    mode: Literal["quick", "standard", "thorough"] = Field(
        default="standard",
        description="Recommended debate mode for this template.",
    )
    tags: list[str] = Field(default_factory=list, description="Keywords for search filtering.")


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

TEMPLATES: list[DebateTemplate] = [
    # Business (3)
    DebateTemplate(
        id="market-expansion",
        title="Market Expansion",
        category="Business",
        icon="🌍",
        query=(
            "Our company is considering expanding into the Southeast Asian market in Q3. "
            "We have a strong product-market fit in our home market, but the new region has "
            "different regulatory requirements, cultural nuances, and established local competitors. "
            "Should we proceed with the expansion, delay, or pursue a different growth strategy?"
        ),
        mode="standard",
        tags=["expansion", "market entry", "growth", "international"],
    ),
    DebateTemplate(
        id="remote-work-policy",
        title="Remote vs. Hybrid Work Policy",
        category="Business",
        icon="🏢",
        query=(
            "Our 500-person company currently operates fully remote since 2020. "
            "Leadership is debating whether to require 3 days per week in-office (hybrid model) "
            "starting next quarter. What are the pros and cons, and what policy should we adopt?"
        ),
        mode="standard",
        tags=["HR", "remote work", "hybrid", "culture", "productivity"],
    ),
    DebateTemplate(
        id="acquisition-decision",
        title="Startup Acquisition",
        category="Business",
        icon="🤝",
        query=(
            "We have the opportunity to acquire a Series B startup for $50M. "
            "The target has complementary technology, a team of 35 engineers, and $8M ARR but is "
            "not yet profitable. Should we proceed with the acquisition, negotiate different terms, "
            "or pursue organic product development instead?"
        ),
        mode="thorough",
        tags=["M&A", "acquisition", "startup", "investment"],
    ),
    # Technology (2)
    DebateTemplate(
        id="cloud-migration",
        title="Cloud Migration Strategy",
        category="Technology",
        icon="☁️",
        query=(
            "Our engineering team needs to migrate a monolithic on-premise application (2M LOC, "
            "500K daily active users) to the cloud. We're evaluating a lift-and-shift approach "
            "vs. a full re-architecture to microservices. Which approach should we take, and what "
            "is the optimal migration timeline?"
        ),
        mode="thorough",
        tags=["cloud", "migration", "microservices", "architecture", "AWS"],
    ),
    DebateTemplate(
        id="build-vs-buy",
        title="Build vs. Buy AI Infrastructure",
        category="Technology",
        icon="🤖",
        query=(
            "Our product roadmap requires advanced AI/ML capabilities for personalisation and "
            "fraud detection. Should we build a proprietary ML platform, purchase an enterprise "
            "solution (e.g. DataRobot, Vertex AI), or use open-source tooling with a small "
            "in-house team? Evaluate cost, time-to-market, and long-term flexibility."
        ),
        mode="standard",
        tags=["AI", "ML", "build vs buy", "infrastructure", "platform"],
    ),
    # Strategy (2)
    DebateTemplate(
        id="pricing-strategy",
        title="Pricing Model Overhaul",
        category="Strategy",
        icon="💰",
        query=(
            "Our SaaS product uses per-seat pricing at $50/user/month. Competitors have moved to "
            "usage-based pricing. Customers are requesting value-based pricing tied to outcomes. "
            "Should we change our pricing model, and if so, what model best aligns with customer "
            "value and our revenue growth targets?"
        ),
        mode="standard",
        tags=["pricing", "SaaS", "revenue", "strategy"],
    ),
    DebateTemplate(
        id="platform-vs-product",
        title="Platform vs. Product Strategy",
        category="Strategy",
        icon="🎯",
        query=(
            "Our company has a successful B2B software product with 1,000 enterprise customers. "
            "We are debating whether to open our platform via public APIs and a marketplace of "
            "third-party integrations (platform play) vs. continuing to build a tightly-integrated "
            "product. What strategy maximises long-term competitive moat and revenue growth?"
        ),
        mode="thorough",
        tags=["platform", "product", "API", "marketplace", "strategy"],
    ),
    # Personal / Career (3)
    DebateTemplate(
        id="career-pivot",
        title="Career Change Decision",
        category="Personal",
        icon="🔄",
        query=(
            "I am a 35-year-old senior software engineer earning $180K with 12 years of experience. "
            "I am considering pivoting to product management. I have an MBA offer from a top-10 "
            "school. Should I pursue the MBA and pivot to PM, stay in engineering and move into "
            "a staff/principal engineer track, or explore other alternatives?"
        ),
        mode="standard",
        tags=["career", "MBA", "product management", "engineering"],
    ),
    DebateTemplate(
        id="startup-vs-big-tech",
        title="Startup vs. Big Tech Job Offer",
        category="Personal",
        icon="⚖️",
        query=(
            "I have two job offers: (1) Senior Engineer at a FAANG company, $320K total comp, "
            "stable WLB, clear growth track; (2) Staff Engineer at a Series A startup, $200K base "
            "+ 0.5% equity (4-year vest), high risk, high upside. I have a family and a mortgage. "
            "Which offer should I take and why?"
        ),
        mode="standard",
        tags=["career", "startup", "big tech", "compensation", "equity"],
    ),
    DebateTemplate(
        id="graduate-school",
        title="Graduate School Decision",
        category="Personal",
        icon="🎓",
        query=(
            "I have been accepted to a top-5 PhD program in Computer Science with full funding "
            "and a $38K annual stipend. Alternatively, I can join a fast-growing ML startup as "
            "an engineer at $160K. I want to work in AI research long-term. Should I pursue "
            "the PhD or take the industry role and build experience?"
        ),
        mode="standard",
        tags=["education", "PhD", "career", "research", "AI"],
    ),
    # Finance (2)
    DebateTemplate(
        id="ipo-timing",
        title="IPO Timing Decision",
        category="Finance",
        icon="📈",
        query=(
            "Our company has $80M ARR growing at 60% YoY, is EBITDA-positive, and has received "
            "inbound interest from underwriters for a public offering. The current market "
            "conditions are uncertain with rising interest rates. Should we IPO in the next "
            "6-12 months, wait for better market conditions, or explore a strategic acquisition?"
        ),
        mode="thorough",
        tags=["IPO", "finance", "public markets", "valuation", "liquidity"],
    ),
    DebateTemplate(
        id="capex-vs-opex",
        title="CapEx vs. OpEx Infrastructure Investment",
        category="Finance",
        icon="🏗️",
        query=(
            "Our infrastructure costs run $3M/year on cloud (OpEx). We can purchase on-premise "
            "servers for a one-time $8M investment (CapEx) that would slash ongoing costs to "
            "$600K/year. Evaluate the financial and operational tradeoffs over a 5-year horizon, "
            "including flexibility, risk, and total cost of ownership."
        ),
        mode="standard",
        tags=["finance", "CapEx", "OpEx", "infrastructure", "TCO"],
    ),
]

# Fast lookup by id
TEMPLATES_BY_ID: dict[str, DebateTemplate] = {t.id: t for t in TEMPLATES}

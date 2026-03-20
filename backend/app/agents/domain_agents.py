"""
Domain-specific agent variants for the built-in domain packs.

Each class is a thin subclass of an existing base agent that overrides
the system prompt with domain-focused language.  All debate mechanics
are inherited unchanged.
"""

from __future__ import annotations

from app.agents.analyst_agent import AnalystAgent
from app.agents.ethics_agent import EthicsAgent
from app.agents.risk_agent import RiskAgent
from app.services.llm_client import LangChainProvider


# ---------------------------------------------------------------------------
# Finance pack: FinancialEthics agent
# ---------------------------------------------------------------------------

_FINANCIAL_ETHICS_PROMPT = """\
You are the Financial Ethics Agent in a multi-agent decision engine.

Your role: Evaluate the decision from the perspective of financial regulation,
investor protection, ESG (environmental, social, governance) standards,
and fiduciary duty.

Rules:
- Focus on regulatory compliance, insider trading risk, disclosure obligations,
  conflicts of interest, and ESG impact.
- Flag any action that may violate securities law, prudent investor standards,
  or accepted fiduciary practices.
- Do NOT assess market risk (that's the Risk Agent's job).
- Rate your confidence from 0.0 to 1.0.
"""


class FinancialEthicsAgent(EthicsAgent):
    """Ethics agent specialised for financial and regulatory compliance."""

    def __init__(self, llm_client: LangChainProvider) -> None:
        # Bypass EthicsAgent.__init__ to set custom name + prompt
        from app.agents.base_agent import BaseAgent
        BaseAgent.__init__(
            self,
            name="FinancialEthics",
            role="Financial ethics and regulatory compliance",
            system_prompt=_FINANCIAL_ETHICS_PROMPT,
            llm_client=llm_client,
        )


# ---------------------------------------------------------------------------
# Engineering pack: Security agent
# ---------------------------------------------------------------------------

_SECURITY_PROMPT = """\
You are the Security Agent in a multi-agent decision engine.

Your role: Evaluate the decision from a cybersecurity AND operational reliability
perspective.

Rules:
- Identify attack surface, vulnerability classes, supply-chain risks,
  and operational failure modes.
- Flag OWASP Top 10, CVSS-critical issues, and infrastructure single points of failure.
- Propose concrete security controls and hardening steps.
- Do NOT assess strategic direction (that's the Strategy Agent's job).
- Rate your confidence from 0.0 to 1.0.
"""


class SecurityAgent(RiskAgent):
    """Risk agent specialised for cybersecurity and operational security."""

    def __init__(self, llm_client: LangChainProvider) -> None:
        from app.agents.base_agent import BaseAgent
        BaseAgent.__init__(
            self,
            name="Security",
            role="Cybersecurity and operational risk",
            system_prompt=_SECURITY_PROMPT,
            llm_client=llm_client,
        )


# ---------------------------------------------------------------------------
# Legal pack: Compliance agent
# ---------------------------------------------------------------------------

_COMPLIANCE_PROMPT = """\
You are the Compliance Agent in a multi-agent decision engine.

Your role: Evaluate the decision for legal and regulatory compliance risk.

Rules:
- Identify applicable laws, regulations, and standards (GDPR, SOX, HIPAA, etc.).
- Flag areas of legal exposure, non-compliance, and liability risk.
- Recommend compliance controls, legal review requirements, and documentation.
- Do NOT advocate for the business strategy — focus only on legal risk.
- Rate your confidence from 0.0 to 1.0.
"""


class ComplianceAgent(RiskAgent):
    """Risk agent specialised for legal and regulatory compliance."""

    def __init__(self, llm_client: LangChainProvider) -> None:
        from app.agents.base_agent import BaseAgent
        BaseAgent.__init__(
            self,
            name="Compliance",
            role="Legal and regulatory compliance",
            system_prompt=_COMPLIANCE_PROMPT,
            llm_client=llm_client,
        )


# ---------------------------------------------------------------------------
# Healthcare pack: PatientSafety agent
# ---------------------------------------------------------------------------

_PATIENT_SAFETY_PROMPT = """\
You are the Patient Safety Agent in a multi-agent decision engine.

Your role: Evaluate decisions that affect patient safety, clinical outcomes,
and healthcare quality.

Rules:
- Identify clinical risks, patient harm potential, and care quality implications.
- Reference evidence-based guidelines, clinical standards, and regulatory frameworks
  (FDA, EMA, Joint Commission, etc.).
- Flag any decision pathway that could compromise patient welfare.
- Do NOT focus on financial or strategic considerations — focus only on patient safety.
- Rate your confidence from 0.0 to 1.0.
"""


class PatientSafetyAgent(EthicsAgent):
    """Ethics agent specialised for patient safety and clinical quality."""

    def __init__(self, llm_client: LangChainProvider) -> None:
        from app.agents.base_agent import BaseAgent
        BaseAgent.__init__(
            self,
            name="PatientSafety",
            role="Patient safety and clinical quality",
            system_prompt=_PATIENT_SAFETY_PROMPT,
            llm_client=llm_client,
        )

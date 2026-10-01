"""
Configuration has one source of truth: no unused settings, and code defaults
mirror the Settings defaults instead of carrying their own numbers.
"""

from app.core.config import Settings
from app.data.domain_packs import DomainPack
from app.orchestrator import nodes


def test_node_timeout_defaults_match_the_settings():
    fields = Settings.model_fields
    assert nodes._PROPOSAL_TIMEOUT == fields["AGENT_PROPOSAL_TIMEOUT"].default
    assert nodes._CRITIQUE_TIMEOUT == fields["AGENT_CRITIQUE_TIMEOUT"].default
    assert nodes._REVISION_TIMEOUT == fields["AGENT_REVISION_TIMEOUT"].default


def test_unused_settings_and_constants_are_gone():
    assert "SECRET_KEY" not in Settings.model_fields
    assert not hasattr(nodes, "_DRIFT_EARLY_STOP_THRESHOLD")  # the gate reads DRIFT_EARLY_STOP_THRESHOLD


def test_domain_focus_does_not_claim_to_reach_the_prompts():
    description = DomainPack.model_fields["domain_focus"].description or ""
    assert "injected" not in description

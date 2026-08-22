"""Operator verbs stay off the model-facing surface (FR-027 / SC-012)."""
from __future__ import annotations

from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE
from audit_agent.reasoning import AUDIT_CHAT_SYSTEM

_FORBIDDEN = (
    "takeover_lease",
    "abandon_session",
    "complete_session",
    "rebind_scope",
    "skip_analysis",
)


def test_operator_verbs_not_offered():
    offered = {k for k, e in AGENT_TOOL_SURFACE.items() if e.offered}
    for verb in _FORBIDDEN:
        assert verb not in offered
        assert verb not in AGENT_TOOL_SURFACE
        assert verb not in AUDIT_CHAT_SYSTEM

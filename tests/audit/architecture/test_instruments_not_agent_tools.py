"""pack/006 US3: measurement instruments are not agent tools."""
from __future__ import annotations

from audit_agent.actions import AuditActionType
from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE
from audit_agent.tool_registry import TOOL_REGISTRY

_INSTRUMENTS = frozenset({
    "bench",
    "proof_bench",
    "capability_screen",
    "scaffold_taxonomy",
    "codegraph",
    "poc_queue_runner",
    "exploit_loop",
})


def test_instruments_absent_from_tool_registry() -> None:
    leaked = sorted(_INSTRUMENTS & set(TOOL_REGISTRY))
    assert leaked == [], f"instrument(s) in TOOL_REGISTRY: {leaked}"


def test_instruments_absent_from_agent_surface() -> None:
    leaked = sorted(_INSTRUMENTS & set(AGENT_TOOL_SURFACE))
    assert leaked == [], f"instrument(s) in AGENT_TOOL_SURFACE: {leaked}"


def test_instruments_absent_from_action_enum() -> None:
    names = {member.value for member in AuditActionType}
    leaked = sorted(_INSTRUMENTS & names)
    assert leaked == [], f"instrument(s) in AuditActionType: {leaked}"

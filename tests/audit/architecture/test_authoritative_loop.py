"""pack/006 US4: kernel loop is agent-path authority; exploit_loop is producer-only."""
from __future__ import annotations

import re
from pathlib import Path

from scripts import exploit_loop as el

from audit_agent.actions import AuditActionType
from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE
from audit_agent.tool_registry import TOOL_REGISTRY

_ASSIGN_VERIFIED = re.compile(r'passed_verified\s*=(?!=)|["\']passed_verified["\']\s*:')


def test_exploit_loop_is_not_on_the_agent_surface() -> None:
    assert "exploit_loop" not in AGENT_TOOL_SURFACE
    assert "exploit_loop" not in TOOL_REGISTRY
    assert "exploit_loop" not in {m.value for m in AuditActionType}


def test_wrap_data_uses_sanitize_and_data_envelope() -> None:
    body = "forge output line 12"
    out = el._wrap_data("read_response", body)
    assert "[DATA START" in out
    assert "[DATA END]" in out
    inner = out.split("[DATA START", 1)[1].split("[DATA END]", 1)[0]
    assert body in inner
    before = out.split("[DATA START", 1)[0]
    assert body not in before


def test_write_marker_is_refused_not_executed() -> None:
    reads, refusals = el._parse_requests("WRITE: contracts/Vault.sol\n")
    assert reads == []
    assert refusals
    assert refusals[0][0] == "WRITE"


def test_loop_does_not_assign_passed_verified() -> None:
    src = Path(el.__file__).read_text(encoding="utf-8")
    assert not _ASSIGN_VERIFIED.search(src)


def test_loop_bounds_are_positive() -> None:
    assert isinstance(el.DEFAULT_BUDGET_CALLS, int) and el.DEFAULT_BUDGET_CALLS > 0
    assert isinstance(el.DEFAULT_SPIN_K, int) and el.DEFAULT_SPIN_K > 0
    assert isinstance(el.DEFAULT_RETRY_CAP, int) and el.DEFAULT_RETRY_CAP > 0

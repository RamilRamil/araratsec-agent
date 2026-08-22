"""skip_target is not skip_analysis (FR-010)."""
from __future__ import annotations

from sr_agent.models.action import Action, ActionClass
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.actions import ACTION_CLASS_MAP, AuditActionType
from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE
from audit_agent.pack import AUDIT_PACK, AUDIT_PRIVILEGED_STATUSES
from audit_agent.reasoning import AUDIT_CHAT_SYSTEM


class _NullSandbox:
    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout="", stderr="")


def test_skip_target_is_read_only_and_not_privileged():
    assert ACTION_CLASS_MAP[AuditActionType.skip_target] is ActionClass.read_only
    assert "skip_analysis" in AUDIT_PRIVILEGED_STATUSES
    assert "skip_analysis" not in AUDIT_CHAT_SYSTEM
    assert "skip_analysis" not in AGENT_TOOL_SURFACE
    out = AUDIT_PACK.dispatch(
        Action(action_type="skip_target", params={"target": "A.sol:f", "reason": "later"}),
        PackContext(scope_root=".", sandbox=_NullSandbox(), wrap_data=wrap_data),
    )
    assert "skip_analysis" not in out.body
    assert out.payloads[0].body.get("transition_type") == "skip"

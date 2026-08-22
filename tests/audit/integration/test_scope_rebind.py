"""Out-of-set paths become gap events; rebind is operator-only (SC-013)."""
from __future__ import annotations

from sr_agent.models.action import Action
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.pack import AUDIT_PACK
from audit_agent.reasoning import AUDIT_CHAT_SYSTEM


class _NullSandbox:
    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout="", stderr="")


def test_check_outside_include_is_gap(tmp_path):
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "Deploy.sol").write_text("contract D {}\n")
    out = AUDIT_PACK.dispatch(
        Action(action_type="run_check", params={"target": "script/Deploy.sol:d"}),
        PackContext(scope_root=tmp_path, sandbox=_NullSandbox(), wrap_data=wrap_data),
    )
    assert out.payloads[0].body.get("transition_type") == "gap"
    assert "rebind_scope" not in AUDIT_CHAT_SYSTEM

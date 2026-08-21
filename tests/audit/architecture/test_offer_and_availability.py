"""US5: offered/available are independent axes (feature 003)."""
from __future__ import annotations

from sr_agent.models.action import Action
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE
from audit_agent.pack import AUDIT_PACK
from audit_agent.reasoning import AUDIT_CHAT_SYSTEM

_UNAVAILABLE = frozenset({
    "build_graph", "decompile_bytecode", "deploy_test_contract",
})


class _FakeSandbox:
    def run(
        self, image, command, mounts=None, timeout_s=None,
        network="none", workdir=None, env=None,
    ):
        return SandboxResult(exit_code=0, stdout="PASS", stderr="")


def _ctx(tmp_path) -> PackContext:
    return PackContext(scope_root=tmp_path, sandbox=_FakeSandbox(), wrap_data=wrap_data)


def test_unavailable_ids_name_precondition_and_payload(tmp_path):
    actual = {k for k, e in AGENT_TOOL_SURFACE.items() if not e.available}
    assert actual == _UNAVAILABLE
    ctx = _ctx(tmp_path)
    for tool_id in _UNAVAILABLE:
        entry = AGENT_TOOL_SURFACE[tool_id]
        assert entry.missing_precondition
        assert entry.offered is False
        out = AUDIT_PACK.dispatch(Action(action_type=tool_id, params={}), ctx)
        assert "status=unavailable" in out
        assert entry.missing_precondition in out
        assert "[STUB]" not in out
        assert "[DATA START" in out


def test_write_execute_unoffered_but_execute_confirmed_still_runs(tmp_path):
    assert "write_poc" not in AUDIT_CHAT_SYSTEM
    assert "run_tests" not in AUDIT_CHAT_SYSTEM
    ctx = _ctx(tmp_path)
    _summary, event = AUDIT_PACK.execute_confirmed(
        Action(action_type="write_poc", params={"finding_id": "F1"}), ctx,
    )
    assert event is not None and event.status == "written"
    _summary2, event2 = AUDIT_PACK.execute_confirmed(
        Action(action_type="run_tests", params={"finding_id": "F1", "test_path": "PoC.t.sol"}),
        ctx,
    )
    assert event2 is not None
    assert event2.status == "passed"


def test_analyze_transactions_unoffered_but_dispatchable(tmp_path):
    assert "analyze_transactions" not in AUDIT_CHAT_SYSTEM
    out = AUDIT_PACK.dispatch(
        Action(
            action_type="analyze_transactions",
            params={"address": "0x" + "ab" * 20, "from_block": 1, "to_block": 2},
        ),
        _ctx(tmp_path),
    )
    assert "[STUB]" not in out
    assert "status=unavailable" not in out
    assert "status=did_not_run" in out
    assert "[DATA START" in out

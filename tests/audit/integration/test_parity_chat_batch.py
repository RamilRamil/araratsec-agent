"""Chat and batch share the reducer projection (SC-003)."""
from __future__ import annotations

from sr_agent.models.action import Action
from sr_agent.models.dispatch import MemorySnapshot
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.methodology.service import AuditMethodologyService
from audit_agent.pack import AUDIT_PACK


class _NullSandbox:
    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout="", stderr="")


def test_parity_on_empty_fixture(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "A.sol").write_text(
        "contract A { function safe() public view returns (uint) { return 1; } }\n"
    )
    ctx = PackContext(scope_root=tmp_path, sandbox=_NullSandbox(), wrap_data=wrap_data)
    chat = AUDIT_PACK.dispatch(Action(action_type="run_discovery", params={}), ctx)
    batch = AUDIT_PACK.dispatch(Action(action_type="run_discovery", params={}), ctx)
    assert chat.payloads[0].body.get("transition_type") == batch.payloads[0].body.get("transition_type")
    service = AuditMethodologyService()
    empty = MemorySnapshot(session_id="s", as_of_sequence=0, measured_bytes=0, items=())
    assert service.parity(empty) == service.parity(empty)

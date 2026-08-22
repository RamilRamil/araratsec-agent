"""DispatchResult wrap and stage-action payloads."""
from __future__ import annotations

from sr_agent.models.action import Action
from sr_agent.models.dispatch import DispatchResult, DispatchStatus
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.pack import AUDIT_PACK


class _NullSandbox:
    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout="", stderr="")


def _ctx(tmp_path) -> PackContext:
    return PackContext(scope_root=tmp_path, sandbox=_NullSandbox(), wrap_data=wrap_data)


def test_read_file_dispatch_returns_dispatch_result(tmp_path):
    path = tmp_path / "Vault.sol"
    path.write_text("contract Vault {}\n")
    out = AUDIT_PACK.dispatch(Action(action_type="read_file", params={"path": str(path)}), _ctx(tmp_path))
    assert isinstance(out, DispatchResult)
    assert out.status is DispatchStatus.ran
    assert "[DATA START" in out.body


def test_stage_ids_return_payload_kinds(tmp_path):
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "Vault.sol").write_text(
        "contract Vault { function withdraw() public { selfdestruct(payable(msg.sender)); } }\n"
    )
    ctx = _ctx(tmp_path)
    discovery = AUDIT_PACK.dispatch(Action(action_type="run_discovery", params={}), ctx)
    assert isinstance(discovery, DispatchResult)
    assert discovery.payloads
    assert discovery.payloads[0].body.get("kind") == "stage_event"
    assert discovery.payloads[0].body.get("transition_type") == "discover"

    synth = AUDIT_PACK.dispatch(Action(action_type="run_synthesis", params={}), ctx)
    assert synth.payloads[0].body.get("transition_type") == "synthesize"


def test_skip_target_requires_reason(tmp_path):
    ctx = _ctx(tmp_path)
    missing = AUDIT_PACK.dispatch(
        Action(action_type="skip_target", params={"target": "Vault.sol:withdraw"}), ctx,
    )
    assert missing.status is DispatchStatus.error
    ok = AUDIT_PACK.dispatch(
        Action(action_type="skip_target", params={"target": "Vault.sol:withdraw", "reason": "out of scope"}),
        ctx,
    )
    assert ok.status is DispatchStatus.ran
    assert ok.payloads[0].body.get("transition_type") == "skip"
    assert "skipped" in ok.body or "out of scope" in ok.body

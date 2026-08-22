"""Relay request id is derived; ingest is put-if-absent (SC-004a / SC-004c)."""
from __future__ import annotations

from sr_agent.models.action import Action
from sr_agent.models.dispatch import DispatchStatus, PendingKind
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.methodology.adapters import set_relay_dir
from audit_agent.pack import AUDIT_PACK


class _NullSandbox:
    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout="", stderr="")


def test_restart_reuses_request_id(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "V.sol").write_text("contract V { function f() public {} }\n")
    relay = tmp_path / "relay"
    set_relay_dir(relay)
    ctx = PackContext(
        scope_root=tmp_path, sandbox=_NullSandbox(), wrap_data=wrap_data,
        operation_id="op-derived-1", transition_key="tk",
    )
    first = AUDIT_PACK.dispatch(Action(action_type="run_check", params={"target": "contracts/V.sol:f"}), ctx)
    assert first.status is DispatchStatus.pending
    assert first.pending is not None
    assert first.pending.kind is PendingKind.external_response
    assert first.pending.correlation_id == "op-derived-1"
    requests = list((relay / "requests").glob("*.md"))
    assert len(requests) == 1
    second = AUDIT_PACK.dispatch(Action(action_type="run_check", params={"target": "contracts/V.sol:f"}), ctx)
    assert second.pending.correlation_id == "op-derived-1"
    assert len(list((relay / "requests").glob("*.md"))) == 1
    set_relay_dir(None)


def test_pack_passes_no_digest_on_ingest():
    from audit_agent import cli as cli_mod

    source = (cli_mod.__file__ and open(cli_mod.__file__, encoding="utf-8").read()) or ""
    assert "put_external_response_if_absent" in source
    assert "body_digest" not in source

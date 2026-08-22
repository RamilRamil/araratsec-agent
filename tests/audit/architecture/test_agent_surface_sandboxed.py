"""US5: every offered id dispatches without a host subprocess (feature 003)."""
from __future__ import annotations

from pathlib import Path

from sr_agent.models.action import Action
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE
from audit_agent.pack import AUDIT_PACK

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analyzer_surface"


class _FakeSandbox:
    def __init__(self, stdout: str) -> None:
        self.calls: list[dict] = []
        self._stdout = stdout

    def run(self, image, command, mounts=None, timeout_s=None, network="none", workdir=None):
        self.calls.append({"image": image, "network": network, "timeout_s": timeout_s})
        return SandboxResult(exit_code=0, stdout=self._stdout, stderr="")


def test_every_offered_id_dispatches_without_host_subprocess(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("host subprocess must not run on the agent path")

    monkeypatch.setattr("subprocess.run", boom)
    monkeypatch.setattr("subprocess.Popen", boom)

    vault = tmp_path / "Vault.sol"
    vault.write_text((_FIXTURES / "Vault.sol").read_text())
    slither_json = (_FIXTURES / "slither.json").read_text()
    mythril_json = (_FIXTURES / "mythril.json").read_text()
    fake = _FakeSandbox(slither_json)
    ctx = PackContext(scope_root=tmp_path, sandbox=fake, wrap_data=wrap_data)

    offered = {k: e for k, e in AGENT_TOOL_SURFACE.items() if e.offered}
    assert "build_graph" not in offered

    params = {
        "read_file": {"path": str(vault)},
        "search_code": {"pattern": "withdraw"},
        "run_slither": {"target": str(vault)},
        "run_mythril": {"target": str(vault)},
        "run_discovery": {},
        "run_check": {"target": "Vault.sol"},
        "run_synthesis": {},
        "skip_target": {"target": "Vault.sol:withdraw", "reason": "out of scope"},
    }
    stdout_by_id = {"run_mythril": mythril_json}

    for tool_id in offered:
        fake._stdout = stdout_by_id.get(tool_id, slither_json)
        out = AUDIT_PACK.dispatch(
            Action(action_type=tool_id, params=params[tool_id]), ctx,
        )
        body = getattr(out, "body", out)
        assert "[STUB]" not in body
        assert "status=unavailable" not in body
        assert "[DATA START" in body

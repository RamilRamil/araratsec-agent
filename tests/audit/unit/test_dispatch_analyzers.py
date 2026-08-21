"""US1: sandboxed analyzers reachable from pack dispatch (feature 003)."""
from __future__ import annotations

from pathlib import Path

from sr_agent.models.action import Action, ValidationStatus
from sr_agent.orchestrator.action import validate_action
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.dispatch import dispatch
from audit_agent.pack import AUDIT_PACK
from audit_agent.tools.static_analysis import parse_mythril_json, parse_slither_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analyzer_surface"


class _FakeSandbox:
    def __init__(self, stdout: str) -> None:
        self._stdout = stdout
        self.calls: list[dict] = []

    def run(self, image, command, mounts=None, timeout_s=None, network="none", workdir=None):
        self.calls.append({
            "image": image, "command": command, "mounts": mounts,
            "timeout_s": timeout_s, "network": network,
        })
        return SandboxResult(exit_code=0, stdout=self._stdout, stderr="")


def _bind_vault(tmp_path: Path) -> Path:
    dst = tmp_path / "Vault.sol"
    dst.write_text((FIXTURES / "Vault.sol").read_text())
    return dst


def _ctx(tmp_path: Path, sandbox: _FakeSandbox) -> PackContext:
    return PackContext(scope_root=tmp_path, sandbox=sandbox, wrap_data=wrap_data)


def test_run_slither_dispatches_parsed_output(tmp_path):
    raw = (FIXTURES / "slither.json").read_text()
    parsed = parse_slither_json(raw)
    vault = _bind_vault(tmp_path)
    fake = _FakeSandbox(raw)
    out = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, fake),
    )
    assert "[STUB]" not in out
    assert "status=unavailable" not in out
    assert "[DATA START" in out
    assert fake.calls
    for finding in parsed:
        assert finding.description in out


def test_run_mythril_dispatches_parsed_output(tmp_path):
    raw = (FIXTURES / "mythril.json").read_text()
    parsed = parse_mythril_json(raw)
    vault = _bind_vault(tmp_path)
    fake = _FakeSandbox(raw)
    out = dispatch(
        Action(action_type="run_mythril", params={"target": str(vault)}),
        _ctx(tmp_path, fake),
    )
    assert "[STUB]" not in out
    assert "status=unavailable" not in out
    assert "[DATA START" in out
    assert fake.calls
    for finding in parsed:
        assert finding.description in out


def test_analyzer_target_outside_scope_rejected(tmp_path):
    fake = _FakeSandbox("")
    outside = tmp_path.parent / "Other.sol"
    result = validate_action(
        Action(action_type="run_slither", params={"target": str(outside)}),
        tmp_path,
        AUDIT_PACK,
    )
    assert result.status is ValidationStatus.rejected
    assert not fake.calls


def test_analyzer_uses_sandbox_not_host(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("host subprocess.run must not run on the agent path")

    monkeypatch.setattr("subprocess.run", boom)
    raw = (FIXTURES / "slither.json").read_text()
    vault = _bind_vault(tmp_path)
    fake = _FakeSandbox(raw)
    out = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, fake),
    )
    assert fake.calls
    assert fake.calls[0]["network"] == "none"
    assert "[STUB]" not in out


def test_dispatch_never_constructs_finding(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dispatch must not construct Finding")

    monkeypatch.setattr("audit_agent.dispatch.Finding", boom)
    monkeypatch.setattr("audit_agent.tools.static_analysis.Finding", boom)
    raw = (FIXTURES / "slither.json").read_text()
    vault = _bind_vault(tmp_path)
    fake = _FakeSandbox(raw)
    out = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, fake),
    )
    assert "[DATA START" in out
    assert "status=ran" in out

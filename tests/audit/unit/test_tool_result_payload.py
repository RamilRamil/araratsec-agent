"""US3: structured tool-result payload (feature 003)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from sr_agent.models.action import Action
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxError, SandboxResult, SandboxTimeout

from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE, MAX_RESULT_ITEMS
from audit_agent.dispatch import dispatch
from audit_agent.pack import AUDIT_PACK

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analyzer_surface"
_STATUS_RE = re.compile(r"status=(\w+)")
_COUNTS_RE = re.compile(r"shown=(\d+) total=(\d+) omitted=(\d+)")


class _FakeSandbox:
    def __init__(self, stdout: str = "", error: BaseException | None = None) -> None:
        self._stdout = stdout
        self._error = error
        self.calls: list[dict] = []

    def run(self, image, command, mounts=None, timeout_s=None, network="none", workdir=None):
        self.calls.append({"timeout_s": timeout_s, "network": network})
        if self._error is not None:
            raise self._error
        return SandboxResult(exit_code=0, stdout=self._stdout, stderr="")


def _bind_vault(tmp_path: Path) -> Path:
    dst = tmp_path / "Vault.sol"
    dst.write_text((_FIXTURES / "Vault.sol").read_text())
    return dst


def _ctx(tmp_path: Path, sandbox: _FakeSandbox) -> PackContext:
    return PackContext(scope_root=tmp_path, sandbox=sandbox, wrap_data=wrap_data)


def _text(out) -> str:
    return out.body if hasattr(out, "body") else out


def _status(out) -> str:
    blob = _text(out)
    m = _STATUS_RE.search(blob)
    assert m, f"no status= field in {blob!r}"
    return m.group(1)


def test_environment_failure_is_did_not_run_not_empty_ran(tmp_path):
    vault = _bind_vault(tmp_path)
    empty = json.dumps({"success": True, "results": {"detectors": []}})
    ran = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, _FakeSandbox(stdout=empty)),
    )
    failed = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, _FakeSandbox(error=SandboxError("Unable to find image slither-sandbox"))),
    )
    assert _status(ran) == "ran"
    assert _status(failed) == "did_not_run"
    assert _status(ran) != _status(failed)
    assert "[DATA START" in _text(ran) and "[DATA START" in _text(failed)


def test_timeout_empty_success_and_unavailable_are_distinct(tmp_path):
    vault = _bind_vault(tmp_path)
    empty = json.dumps({"success": True, "results": {"detectors": []}})
    ran = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, _FakeSandbox(stdout=empty)),
    )
    timed = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, _FakeSandbox(error=SandboxTimeout("Sandbox exceeded 30.0s"))),
    )
    unavailable = AUDIT_PACK.dispatch(
        Action(action_type="build_graph", params={}),
        _ctx(tmp_path, _FakeSandbox()),
    )
    slither_err = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, _FakeSandbox(stdout="")),
    )
    assert _status(ran) == "ran"
    assert _status(timed) == "timeout"
    assert _status(unavailable) == "unavailable"
    assert _status(slither_err) == "did_not_run"
    for blob in (ran, timed, unavailable, slither_err):
        text = _text(blob)
        assert "[DATA START" in text and "[DATA END]" in text
        assert "[STUB]" not in text


def test_oversized_detector_list_emits_truncation_fields(tmp_path):
    vault = _bind_vault(tmp_path)
    n = MAX_RESULT_ITEMS + 8
    detectors = [
        {
            "check": f"c{i}",
            "impact": "Low",
            "confidence": "High",
            "description": f"finding number {i} " + ("x" * 40),
        }
        for i in range(n)
    ]
    raw = json.dumps({"success": True, "results": {"detectors": detectors}})
    out = dispatch(
        Action(action_type="run_slither", params={"target": str(vault)}),
        _ctx(tmp_path, _FakeSandbox(stdout=raw)),
    )
    m = _COUNTS_RE.search(_text(out))
    assert m, f"missing shown/total/omitted in {_text(out)!r}"
    shown, total, omitted = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    assert total == n
    assert omitted > 0
    assert shown + omitted == total
    assert "[DATA START" in _text(out)
    assert AGENT_TOOL_SURFACE["run_slither"].offered

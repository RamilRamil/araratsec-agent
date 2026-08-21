"""US3: every blocking offered analyzer honors chat_tool_timeout_s (feature 003)."""
from __future__ import annotations

from pathlib import Path

from sr_agent.models.action import Action
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxTimeout

from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE
from audit_agent.config import config
from audit_agent.dispatch import dispatch

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analyzer_surface"
_BLOCKING = ("run_slither", "run_mythril")


class _TimeoutSandbox:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, image, command, mounts=None, timeout_s=None, network="none", workdir=None):
        self.calls.append({"timeout_s": timeout_s})
        raise SandboxTimeout(f"Sandbox exceeded {timeout_s}s")


def test_each_blocking_offered_analyzer_returns_timeout_within_bound(tmp_path):
    vault = tmp_path / "Vault.sol"
    vault.write_text((_FIXTURES / "Vault.sol").read_text())
    bound = config.chat_tool_timeout_s
    assert bound < 300.0
    for tool_id in _BLOCKING:
        entry = AGENT_TOOL_SURFACE[tool_id]
        assert entry.offered and entry.available
        fake = _TimeoutSandbox()
        ctx = PackContext(scope_root=tmp_path, sandbox=fake, wrap_data=wrap_data)
        out = dispatch(
            Action(action_type=tool_id, params={"target": str(vault)}),
            ctx,
        )
        assert fake.calls
        assert fake.calls[0]["timeout_s"] == bound
        assert "status=timeout" in out
        assert "status=unavailable" not in out
        assert "[DATA START" in out
        assert "[STUB]" not in out

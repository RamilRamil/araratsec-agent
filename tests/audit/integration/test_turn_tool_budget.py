"""Per-turn tool budget is loop-local (feature 003, T037)."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

from sr_agent.llm_core.chat_reasoning import ReasoningOutcome
from sr_agent.llm_core.schemas import AgentAction
from sr_agent.memory.episodic import EpisodicMemory
from sr_agent.orchestrator.loop import OrchestratorLoop
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.pack import AUDIT_PACK
from audit_agent.session import AuditInput, AuditSession, Principal

_KEY = bytes(range(32))
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analyzer_surface"


class FakeProvider:
    def __init__(self, *outcomes):
        self._q = list(outcomes)

    def complete(self, messages):
        return self._q.pop(0)


class _FixtureSandbox:
    def __init__(self, stdout: str) -> None:
        self._stdout = stdout

    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout=self._stdout, stderr="")


def test_run_turn_increments_tool_calls_by_one(tmp_path):
    vault = tmp_path / "Vault.sol"
    vault.write_text((_FIXTURES / "Vault.sol").read_text())
    slither_json = (_FIXTURES / "slither.json").read_text()
    provider = FakeProvider(
        ReasoningOutcome(
            kind="action",
            agent_action=AgentAction(
                next_action="run_slither",
                tool_params={"target": str(vault)},
            ),
            tier="local",
        ),
        ReasoningOutcome(
            kind="action",
            agent_action=AgentAction(next_action="complete", reasoning_summary="done"),
            tier="local",
        ),
    )
    memory = EpisodicMemory(memory_root=tmp_path / "mem", secret_key=_KEY)
    principal = Principal(user_id="u", platform="cli", project_id="proj")
    audit_session = AuditSession(
        principal=principal, audit_input=AuditInput(path=tmp_path, principal=principal),
    )
    loop = OrchestratorLoop(
        audit_session, memory, tmp_path,
        pack=AUDIT_PACK, reasoning_provider=provider,
        confirmations_dir=tmp_path / "conf",
        sandbox=_FixtureSandbox(slither_json),
    )
    result = loop.run_turn("audit Vault.withdraw", system_prompt="")
    assert result.status == "completed"
    assert result.tool_calls == 1

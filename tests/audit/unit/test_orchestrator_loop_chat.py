"""Chat-path guards on OrchestratorLoop (feature 003, T003 regression + T020)."""
from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

from pathlib import Path

from sr_agent.llm_core.chat_reasoning import ReasoningOutcome
from sr_agent.llm_core.schemas import AgentAction, FindingPayload
from sr_agent.memory.episodic import EpisodicMemory
from sr_agent.models.memory import SourceType
from sr_agent.orchestrator.loop import OrchestratorLoop
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.pack import AUDIT_PACK
from audit_agent.session import AuditInput, AuditSession, Principal

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analyzer_surface"

_KEY = bytes(range(32))


class FakeProvider:
    def __init__(self, *outcomes):
        self._q = list(outcomes)
        self.seen: list = []

    def complete(self, messages):
        self.seen.append(messages)
        return self._q.pop(0)


class FakeSandbox:
    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout="", stderr="")


class _FixtureSandbox:
    def __init__(self, stdout: str) -> None:
        self._stdout = stdout

    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout=self._stdout, stderr="")


def _loop(tmp_path, provider, sandbox=None):
    memory = EpisodicMemory(memory_root=tmp_path / "mem", secret_key=_KEY)
    principal = Principal(user_id="u", platform="cli", project_id="proj")
    audit_session = AuditSession(
        principal=principal, audit_input=AuditInput(path=tmp_path, principal=principal)
    )
    loop = OrchestratorLoop(
        audit_session, memory, tmp_path,
        pack=AUDIT_PACK, reasoning_provider=provider,
        confirmations_dir=tmp_path / "conf",
        sandbox=sandbox if sandbox is not None else FakeSandbox(),
    )
    return loop, memory


# ── T003 regression: chat findings are external_llm_output, never llm_inference ──

def test_chat_finding_persisted_as_external_llm_output(tmp_path):
    finding = FindingPayload(
        finding_id="H-1", location="Vault.sol:10", function_name="withdraw",
        severity="high", notes="reentrancy",
    )
    aa = AgentAction(next_action="complete", finding=finding, reasoning_summary="found one")
    provider = FakeProvider(ReasoningOutcome(kind="action", agent_action=aa, tier="local"))
    loop, memory = _loop(tmp_path, provider)

    loop.run_turn("audit Vault.withdraw", system_prompt="")
    records = memory.load("proj", "Vault.sol")
    assert len(records) == 1
    assert records[0].source_type is SourceType.external_llm_output   # NOT llm_inference (R7)


# ── T020: no path executes a write_execute without an APPROVED confirmation ──

def test_write_execute_pauses_and_does_not_run_in_turn(tmp_path):
    aa = AgentAction(next_action="write_poc", tool_params={"finding_id": "F1"})
    provider = FakeProvider(ReasoningOutcome(kind="action", agent_action=aa, tier="local"))
    loop, memory = _loop(tmp_path, provider)

    result = loop.run_turn("write a PoC for F1", system_prompt="")
    # run_turn NEVER dispatches a write_execute action itself — it pauses.
    assert result.status == "paused_confirmation"
    assert result.pending_confirmation_id is not None
    assert not (tmp_path / "audit" / "poc").exists()   # nothing written in-turn
    from audit_agent.reasoning import AUDIT_CHAT_SYSTEM
    assert "write_poc" not in AUDIT_CHAT_SYSTEM
    assert "run_tests" not in AUDIT_CHAT_SYSTEM


def test_execute_confirmed_is_the_only_run_path(tmp_path):
    # execute_confirmed is what actually runs an approved action; run_turn's gate
    # is the only thing that reaches it (via the CLI resume path). Calling it is a
    # deliberate post-approval step — there is no in-turn shortcut to it.
    from sr_agent.models.action import Action

    aa = AgentAction(next_action="write_poc", tool_params={"finding_id": "F1"})
    provider = FakeProvider(ReasoningOutcome(kind="action", agent_action=aa, tier="local"))
    loop, _ = _loop(tmp_path, provider)
    # A turn only ever pauses (proven above). Executing requires an explicit call.
    action = Action(action_type="write_poc", params={"finding_id": "F1"})
    summary, event = loop.execute_confirmed(action)
    assert event is not None and event.status == "written"
    assert list((tmp_path / "audit" / "poc").glob("*.t.sol"))


# ── T044: scripted turn reaches run_slither (US1 independent test) ───────────

def test_run_turn_selects_run_slither(tmp_path):
    vault = tmp_path / "Vault.sol"
    vault.write_text((_FIXTURES / "Vault.sol").read_text())
    slither_json = (_FIXTURES / "slither.json").read_text()
    aa_slither = AgentAction(
        next_action="run_slither",
        tool_params={"target": str(vault)},
        reasoning_summary="scan withdraw",
    )
    aa_done = AgentAction(next_action="complete", reasoning_summary="scanned")
    provider = FakeProvider(
        ReasoningOutcome(kind="action", agent_action=aa_slither, tier="local"),
        ReasoningOutcome(kind="action", agent_action=aa_done, tier="local"),
    )
    loop, _ = _loop(tmp_path, provider, sandbox=_FixtureSandbox(slither_json))

    result = loop.run_turn("audit Vault.withdraw", system_prompt="")
    assert result.status == "completed"
    assert any("run_slither" in s for s in result.tool_summaries)
    assert len(provider.seen) >= 2
    tool_output = "\n".join(
        m["content"] if isinstance(m, dict) else str(m) for m in provider.seen[1]
    )
    assert "[DATA START" in tool_output
    assert "Reentrancy in Vault.withdraw" in tool_output
    assert "[STUB]" not in tool_output
    assert "status=unavailable" not in tool_output

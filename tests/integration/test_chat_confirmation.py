"""US3: irreversible actions require OOB confirmation (feature 003, T019, SC-003)."""
from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

from audit_agent.cli import handle_turn, resume_confirmation
from sr_agent.llm_core.chat_reasoning import ReasoningOutcome
from sr_agent.llm_core.schemas import AgentAction
from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.session import AuditInput, AuditSession, Principal
from sr_agent.models.chat import ChatSession
from sr_agent.orchestrator.confirmation import resolve_confirmation
from sr_agent.orchestrator.loop import OrchestratorLoop
from audit_agent.pack import AUDIT_PACK
from sr_agent.tools.sandbox import SandboxResult

_KEY = bytes(range(32))


class FakeProvider:
    def __init__(self, outcome):
        self._outcome = outcome

    def complete(self, messages):
        return self._outcome


class FakeSandbox:
    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout="", stderr="")


def _setup(tmp_path):
    memory = EpisodicMemory(memory_root=tmp_path / "mem", secret_key=_KEY)
    principal = Principal(user_id="u", platform="cli", project_id="proj")
    session = ChatSession(principal=principal)
    audit_session = AuditSession(
        principal=principal, audit_input=AuditInput(path=tmp_path, principal=principal)
    )
    aa = AgentAction(next_action="write_poc", tool_params={"finding_id": "F1"})
    loop = OrchestratorLoop(
        audit_session, memory, tmp_path,
        pack=AUDIT_PACK, reasoning_provider=FakeProvider(ReasoningOutcome(kind="action", agent_action=aa, tier="local")),
        confirmations_dir=tmp_path / "conf",
        sandbox=FakeSandbox(), poc_dir=tmp_path / "audit" / "poc",
    )
    return loop, session, memory


def _poc_written(tmp_path) -> bool:
    d = tmp_path / "audit" / "poc"
    return d.exists() and len(list(d.glob("*.t.sol"))) > 0


def test_never_executes_before_approval(tmp_path):
    loop, session, memory = _setup(tmp_path)
    result = handle_turn(loop, session, memory, "write a PoC for F1")
    assert result.status == "paused_confirmation"
    assert not _poc_written(tmp_path)               # SC-003: nothing runs pre-approval


def test_approve_proceeds(tmp_path):
    loop, session, memory = _setup(tmp_path)
    result = handle_turn(loop, session, memory, "write a PoC for F1")
    resolve_confirmation(result.pending_confirmation_id, tmp_path / "conf", approve=True)
    resume_confirmation(loop, session, memory)
    assert _poc_written(tmp_path)                    # runs only after out-of-band approval


def test_reject_does_not_execute(tmp_path):
    loop, session, memory = _setup(tmp_path)
    result = handle_turn(loop, session, memory, "write a PoC for F1")
    resolve_confirmation(result.pending_confirmation_id, tmp_path / "conf", approve=False)
    msg = resume_confirmation(loop, session, memory)
    assert "not executed" in msg
    assert not _poc_written(tmp_path)


def test_still_pending_is_fail_safe_not_executed(tmp_path):
    # Fail-safe: resuming while the confirmation is still unresolved runs nothing.
    loop, session, memory = _setup(tmp_path)
    handle_turn(loop, session, memory, "write a PoC for F1")
    msg = resume_confirmation(loop, session, memory)   # never approved
    assert "pending" in msg
    assert not _poc_written(tmp_path)
    assert session.status == "paused_confirmation"     # stays paused, not executed

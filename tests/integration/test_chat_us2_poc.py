"""US2 integration: PoC write+run through the OOB gate (feature 003, T015)."""
from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

from pathlib import Path

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
    def __init__(self, *outcomes):
        self._q = list(outcomes)

    def complete(self, messages):
        return self._q.pop(0)


class FakeSandbox:
    """Stands in for DockerSandbox — no real container."""
    def __init__(self, exit_code: int = 0):
        self._exit = exit_code

    def run(self, image, command, mounts=None, timeout_s=None, network="none", workdir=None, env=None):
        return SandboxResult(exit_code=self._exit, stdout="[PASS] test_exploit()", stderr="")


def _action(next_action, **params) -> ReasoningOutcome:
    aa = AgentAction(next_action=next_action, tool_params=params)
    return ReasoningOutcome(kind="action", agent_action=aa, tier="local")


def _setup(tmp_path, provider, sandbox=None):
    memory = EpisodicMemory(memory_root=tmp_path / "mem", secret_key=_KEY)
    principal = Principal(user_id="u", platform="cli", project_id="proj")
    session = ChatSession(principal=principal)
    audit_session = AuditSession(
        principal=principal, audit_input=AuditInput(path=tmp_path, principal=principal)
    )
    loop = OrchestratorLoop(
        audit_session, memory, tmp_path,
        pack=AUDIT_PACK, reasoning_provider=provider,
        session_facts_provider=lambda: None,
        confirmations_dir=tmp_path / "conf",
        sandbox=sandbox or FakeSandbox(),
    )
    return loop, session, memory


def _poc_status_events(memory, session):
    records = memory.load("proj", f"chat:{session.session_id}")
    return [r.payload for r in records if r.payload_kind == "poc_status"]


def test_write_poc_gated_then_written_on_approval(tmp_path):
    loop, session, memory = _setup(tmp_path, FakeProvider(_action("write_poc", finding_id="F1")))

    # 1. The request PAUSES for confirmation and writes NOTHING yet (SC-003).
    result = handle_turn(loop, session, memory, "write a PoC for F1")
    assert result.status == "paused_confirmation"
    assert result.pending_action_type == "write_poc"
    assert result.pending_action_params == {"finding_id": "F1"}
    assert not (tmp_path / "audit" / "poc").exists() or list((tmp_path / "audit" / "poc").glob("*.t.sol")) == []
    assert _poc_status_events(memory, session) == []

    # 2. Approve out-of-band, then resume.
    resolve_confirmation(result.pending_confirmation_id, tmp_path / "conf", approve=True)
    summary = resume_confirmation(loop, session, memory)

    # 3. Now the PoC exists and a mechanical 'written' status is recorded.
    poc_files = list((tmp_path / "audit" / "poc").glob("*.t.sol"))
    assert len(poc_files) == 1
    assert "written" in summary or "PoC written" in summary
    events = _poc_status_events(memory, session)
    assert len(events) == 1 and events[0]["status"] == "written"
    assert session.status == "active" and session.pending_confirmation_id is None


def test_write_poc_rejected_not_executed(tmp_path):
    loop, session, memory = _setup(tmp_path, FakeProvider(_action("write_poc", finding_id="F1")))
    result = handle_turn(loop, session, memory, "write a PoC for F1")
    resolve_confirmation(result.pending_confirmation_id, tmp_path / "conf", approve=False)
    summary = resume_confirmation(loop, session, memory)

    assert "not executed" in summary
    assert list((tmp_path / "audit" / "poc").glob("*.t.sol")) == [] if (tmp_path / "audit" / "poc").exists() else True
    assert _poc_status_events(memory, session) == []
    assert session.status == "active"


def test_run_tests_passed_records_status(tmp_path):
    loop, session, memory = _setup(
        tmp_path,
        FakeProvider(_action("run_tests", finding_id="F1", test_path="audit/poc/F1.t.sol")),
        sandbox=FakeSandbox(exit_code=0),
    )
    result = handle_turn(loop, session, memory, "run the PoC for F1")
    assert result.status == "paused_confirmation"
    resolve_confirmation(result.pending_confirmation_id, tmp_path / "conf", approve=True)
    summary = resume_confirmation(loop, session, memory)

    assert "PASSED" in summary
    events = _poc_status_events(memory, session)
    assert len(events) == 1 and events[0]["status"] == "passed"
    # a passed PoC is a reproduction, not a verdict — recorded as tool_output only
    records = memory.load("proj", f"chat:{session.session_id}")
    poc_rec = [r for r in records if r.payload_kind == "poc_status"][0]
    assert poc_rec.source_type.value == "tool_output"

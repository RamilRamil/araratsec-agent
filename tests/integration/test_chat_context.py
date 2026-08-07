"""US4: long-session grounding + findings roadmap view (feature 003, T021, SC-004)."""
from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

from audit_agent.cli import _facts_to_str, handle_turn
from sr_agent.llm_core.chat_reasoning import ReasoningOutcome
from sr_agent.llm_core.schemas import AgentAction, FindingPayload
from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.session import AuditInput, AuditSession, Principal
from sr_agent.models.chat import ChatSession, PoCStatusEvent
from sr_agent.orchestrator.chat_session import record_poc_status, render_roadmap
from sr_agent.orchestrator.loop import OrchestratorLoop
from audit_agent.pack import AUDIT_PACK

_KEY = bytes(range(32))


class CapturingProvider:
    """Echoes plain answers but records the messages it was handed each turn."""
    def __init__(self, *outcomes):
        self._q = list(outcomes)
        self.last_messages = None

    def complete(self, messages):
        self.last_messages = messages
        return self._q.pop(0)


def _answer(text="ok") -> ReasoningOutcome:
    return ReasoningOutcome(kind="action", agent_action=AgentAction(next_action="complete", reasoning_summary=text), tier="local")


def _finding_turn() -> ReasoningOutcome:
    f = FindingPayload(finding_id="F1", location="Vault.sol:10", function_name="withdraw", severity="high", notes="x")
    return ReasoningOutcome(kind="action", agent_action=AgentAction(next_action="complete", finding=f, reasoning_summary="found F1"), tier="local")


def _setup(tmp_path, provider):
    memory = EpisodicMemory(memory_root=tmp_path / "mem", secret_key=_KEY)
    principal = Principal(user_id="u", platform="cli", project_id="proj")
    session = ChatSession(principal=principal)
    audit_session = AuditSession(principal=principal, audit_input=AuditInput(path=tmp_path, principal=principal))
    loop = OrchestratorLoop(
        audit_session, memory, tmp_path,
        pack=AUDIT_PACK, reasoning_provider=provider,
        session_facts_provider=lambda: _facts_to_str(session.session_facts),
        confirmations_dir=tmp_path / "conf",
    )
    return loop, session, memory


def test_early_fact_survives_many_later_turns(tmp_path):
    provider = CapturingProvider(_finding_turn(), *[_answer() for _ in range(8)])
    loop, session, memory = _setup(tmp_path, provider)

    handle_turn(loop, session, memory, "audit Vault.withdraw")   # establishes F1
    for _ in range(8):
        handle_turn(loop, session, memory, "keep going")

    # The grounding fact established on turn 1 is still fed to the model 8 turns later.
    facts_block = "\n".join(
        m["content"] for m in provider.last_messages if "session_facts" in m.get("content", "")
    )
    assert "F1" in facts_block
    assert session.session_facts.known_finding_ids == ["F1"]


def test_roadmap_renders_latest_status_and_skip_reasons(tmp_path):
    _, session, memory = _setup(tmp_path, CapturingProvider())
    record_poc_status(session, PoCStatusEvent(finding_id="F1", status="written", poc_path="audit/poc/F1.t.sol"), memory)
    record_poc_status(session, PoCStatusEvent(finding_id="F1", status="passed"), memory)   # latest wins
    record_poc_status(session, PoCStatusEvent(finding_id="L6", status="skipped", skip_reason="floor-gated, OOS"), memory)

    table = render_roadmap(session.session_id, "proj", memory)
    assert "| F1 | passed |" in table
    assert "| L6 | skipped | floor-gated, OOS |" in table
    assert "written" not in table   # superseded by the later 'passed'

"""US1 integration: sr-agent chat Q&A + read-only dispatch (feature 003, T011/T013)."""
from __future__ import annotations

import os

# config requires these at import time; set before importing sr_agent.* (chat mode
# itself needs no paid API — a dummy key just satisfies the config gate, T027 will
# make it optional).
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

from pathlib import Path

from click.testing import CliRunner

from audit_agent.cli import cli, format_reply, handle_turn
from sr_agent.llm_core.chat_reasoning import ReasoningOutcome
from sr_agent.llm_core.schemas import AgentAction
from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.session import AuditInput, AuditSession, Principal
from sr_agent.models.chat import ChatSession, RoutingDecision
from sr_agent.orchestrator.chat_session import load_turns
from sr_agent.orchestrator.loop import OrchestratorLoop
from audit_agent.pack import AUDIT_PACK

_KEY = bytes(range(32))


class FakeProvider:
    """Returns a queued sequence of ReasoningOutcomes (no Ollama)."""
    def __init__(self, *outcomes):
        self._q = list(outcomes)

    def complete(self, messages):
        return self._q.pop(0)


def _local(tier="local") -> RoutingDecision:
    return RoutingDecision(tier=tier)


def _answer(text: str) -> ReasoningOutcome:
    aa = AgentAction(next_action="complete", reasoning_summary=text)
    return ReasoningOutcome(kind="action", agent_action=aa, tier="local")


def _setup(tmp_path, provider):
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
    )
    return loop, session, memory


def test_qa_turn_answers_and_shows_tier(tmp_path):
    loop, session, memory = _setup(tmp_path, FakeProvider(
        _answer("Finding F1 is a reentrancy bug in Vault.withdraw.")
    ))
    result = handle_turn(loop, session, memory, "what is finding F1?")

    assert result.status == "completed"
    assert result.routing.tier == "local"
    assert result.pending_confirmation_id is None          # no write_execute was invoked
    reply = format_reply(result)
    assert reply.startswith("[local]")                     # tier always visible (FR-010/SC-006)
    assert "reentrancy" in reply
    # the turn was persisted and is resumable
    assert [t.user_message for t in load_turns(session.session_id, "proj", memory)] == ["what is finding F1?"]


def test_empty_findings_does_not_invent(tmp_path):
    loop, session, memory = _setup(tmp_path, FakeProvider(
        _answer("No findings are recorded for this project yet.")
    ))
    result = handle_turn(loop, session, memory, "list the findings")
    assert result.status == "completed"
    assert result.findings == []                           # nothing invented/persisted
    assert session.session_facts.known_finding_ids == []


def test_read_only_dispatch_then_answer(tmp_path):
    # A file the read_file tool can read within the audit root.
    (tmp_path / "Foo.sol").write_text("contract Foo {}\n", encoding="utf-8")
    read_action = AgentAction(next_action="read_file", tool_params={"path": str(tmp_path / "Foo.sol")})
    loop, session, memory = _setup(tmp_path, FakeProvider(
        ReasoningOutcome(kind="action", agent_action=read_action, tier="local"),
        _answer("Foo.sol defines an empty contract Foo."),
    ))
    result = handle_turn(loop, session, memory, "show me Foo.sol")
    assert result.status == "completed"
    assert result.tool_calls == 1                          # one read-only dispatch happened
    assert result.pending_confirmation_id is None          # read_file is not gated


def test_chat_command_is_registered():
    res = CliRunner().invoke(cli, ["chat", "--help"])
    assert res.exit_code == 0
    assert "Interactive chat" in res.output

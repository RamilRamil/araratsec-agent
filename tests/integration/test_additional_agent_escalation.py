"""Spec 019 US3: escalation consults the ADDITIONAL agent, with the gate intact.

Part A drives `ChatReasoningProvider._escalate` directly (additional → AgentAction;
None → relay; failing additional → relay fallback, C1). Part B proves an
additional-agent outcome (kind="action") is still gated by run_turn: a privileged
action pauses for confirmation (Constitution II), and its turn is external_llm_output.
"""
from __future__ import annotations

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

import json
from types import SimpleNamespace

from sr_agent.llm_core.chat_reasoning import ChatReasoningProvider, ReasoningOutcome
from sr_agent.llm_core.gemini_client import GeminiUnavailable
from sr_agent.llm_core.local_client import ModelUnavailableError
from sr_agent.llm_core.schemas import AgentAction
from sr_agent.memory.episodic import EpisodicMemory
from sr_agent.models.memory import SourceType
from sr_agent.orchestrator.loop import OrchestratorLoop
from audit_agent.pack import AUDIT_PACK
from audit_agent.session import AuditInput, AuditSession, Principal
from sr_agent.tools.sandbox import SandboxResult

_ESCALATE_JSON = json.dumps({
    "next_action": "escalate", "escalation_trigger": "unknown_pattern",
    "reasoning_summary": "beyond me",
})
_ADDITIONAL_JSON = json.dumps({"next_action": "complete", "reasoning_summary": "second opinion"})


def _NO_GUARD(**_k):  # deterministic guard disabled → drive the self-report escalate path
    return SimpleNamespace(triggered=False, trigger=None)


class _FakeMain:
    def ready(self): return True
    def generate(self, prompt, fmt=None, options=None): return _ESCALATE_JSON


class _FakeAdditional:
    def __init__(self, out): self._out = out
    def generate(self, prompt, fmt=None, options=None): return self._out


class _RaisingAdditional:
    def __init__(self, exc): self._exc = exc
    def generate(self, prompt, fmt=None, options=None): raise self._exc


def _provider(tmp_path, additional):
    return ChatReasoningProvider(
        local=_FakeMain(), session=SimpleNamespace(session_id="s1"),
        relay_dir=tmp_path, additional=additional, evaluate_fn=_NO_GUARD,
    )


# ── Part A: _escalate routing ────────────────────────────────────────────────

def test_additional_consulted_returns_action(tmp_path):
    out = _provider(tmp_path, _FakeAdditional(_ADDITIONAL_JSON)).complete([{"content": "hi"}])
    assert out.kind == "action" and out.tier == "additional"
    assert out.agent_action.next_action == "complete"


def test_no_additional_falls_back_to_relay(tmp_path):
    out = _provider(tmp_path, None).complete([{"content": "hi"}])
    assert out.kind == "paused_relay" and out.tier == "relay"


def test_failing_additional_falls_back_to_relay(tmp_path):
    for exc in (ModelUnavailableError("down"), GeminiUnavailable("no key")):
        out = _provider(tmp_path, _RaisingAdditional(exc)).complete([{"content": "hi"}])
        assert out.kind == "paused_relay", f"{type(exc).__name__} should fall back to relay"


# ── Part B: the gate applies to an additional-agent outcome ──────────────────

class _ScriptedProvider:
    def __init__(self, outcome): self._o = outcome
    def complete(self, messages): return self._o


class _FakeSandbox:
    def run(self, *a, **k): return SandboxResult(exit_code=0, stdout="", stderr="")


def _loop(tmp_path, provider):
    memory = EpisodicMemory(memory_root=tmp_path / "mem", secret_key=bytes(range(32)))
    principal = Principal(user_id="u", platform="cli", project_id="proj")
    session = AuditSession(principal=principal,
                           audit_input=AuditInput(path=tmp_path, principal=principal))
    loop = OrchestratorLoop(
        session, memory, tmp_path, pack=AUDIT_PACK, reasoning_provider=provider,
        confirmations_dir=tmp_path / "conf", sandbox=_FakeSandbox(),
        poc_dir=tmp_path / "audit" / "poc",
    )
    return loop


def test_additional_privileged_action_still_pauses_for_confirmation(tmp_path):
    # An additional-agent proposal (tier="additional") to run a write_execute action
    # must still pause for the human gate — the additional agent cannot self-authorize.
    aa = AgentAction(next_action="write_poc", tool_params={"finding_id": "F1"})
    outcome = ReasoningOutcome(kind="action", agent_action=aa, tier="additional")
    result = _loop(tmp_path, _ScriptedProvider(outcome)).run_turn("go", system_prompt="")
    assert result.status == "paused_confirmation"

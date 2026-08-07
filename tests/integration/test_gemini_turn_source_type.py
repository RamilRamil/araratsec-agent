"""Spec 018 US1 (FR-006): a Gemini-served turn is external_llm_output.

The trust status is STRUCTURAL: `ChatTurn.source_type` defaults to
external_llm_output and its validator forbids human_input / llm_inference —
regardless of which client (local / Gemini / relay) produced the content. So
Gemini output can never be elevated to a human-authored input. This test pins
that invariant on the model an operator-selected Gemini turn flows through.
"""
from __future__ import annotations

import os

os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

import pytest

from sr_agent.llm_core.schemas import AgentAction
from sr_agent.models.chat import ChatTurn
from sr_agent.models.memory import SourceType


def _gemini_action() -> AgentAction:
    # An AgentAction as if parsed from a GeminiClient.generate() response.
    return AgentAction(next_action="respond", reasoning_summary="from gemini")


def test_gemini_turn_defaults_to_external_llm_output():
    turn = ChatTurn(session_id="s1", user_message="hi", agent_action=_gemini_action())
    assert turn.source_type == SourceType.external_llm_output


def test_gemini_turn_cannot_be_human_input():
    with pytest.raises(ValueError):
        ChatTurn(
            session_id="s1", user_message="hi", agent_action=_gemini_action(),
            source_type=SourceType.human_input,
        )


def test_gemini_turn_cannot_be_llm_inference():
    with pytest.raises(ValueError):
        ChatTurn(
            session_id="s1", user_message="hi", agent_action=_gemini_action(),
            source_type=SourceType.llm_inference,
        )

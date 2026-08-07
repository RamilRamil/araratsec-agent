"""Feature 015 US1 (integration): a tool-calling round-trip that returns no Solidity falls
back to the marker protocol for that finding, rather than emitting an empty PoC.
"""
import scripts.poc_queue_runner as pqr
from sr_agent.eval.tracer import NOOP_TRACER

_SOL = "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.28;\ncontract P { function test_x() public {} }"


class _FakeClient:
    """chat() (tool mode) returns no code; generate() (marker fallback) returns real Solidity."""
    model = "fake"

    def chat(self, messages, tools=None, options=None, **k):
        return {"content": "", "tool_calls": []}

    def generate(self, prompt, options=None, **k):
        return f"```solidity\n{_SOL}\n```"

    def supports_tools(self, *a, **k):
        return True


def test_tool_empty_falls_back_to_marker():
    code = pqr._traced_round_trip(
        "draft", _FakeClient(), "PROMPT", symbol_index=None, lookup_budget=0,
        on_lookup=None, protocol_mode="tool", tracer=NOOP_TRACER, trace=None)
    # the tool round-trip produced nothing → marker fallback supplied the real code
    assert code == _SOL


def test_marker_mode_unaffected():
    # a marker-mode round-trip whose generate returns Solidity extracts it (no fallback path)
    code = pqr._traced_round_trip(
        "draft", _FakeClient(), "PROMPT", symbol_index=None, lookup_budget=0,
        on_lookup=None, protocol_mode="marker", tracer=NOOP_TRACER, trace=None)
    assert code == _SOL

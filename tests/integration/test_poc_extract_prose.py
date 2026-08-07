"""Feature 015 US1 (integration): the real draft path extracts clean Solidity from a
prose-wrapped model reply, and a code-free reply fails the draft without writing a file.
Offline — a scripted fake client, no model/Docker/network.
"""
from __future__ import annotations

import types
from pathlib import Path

import scripts.poc_queue_runner as pqr
from sr_agent.eval.tracer import NOOP_TRACER

TASK = {"id": "X-01", "title": "t", "location": "", "description": "a bug"}
_SOL = "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.28;\ncontract P { function test_x() public {} }"


class _FakeClient:
    model = "fake"

    def __init__(self, gen: str):
        self._gen = gen

    def generate(self, prompt, options=None, **k):
        return self._gen

    def supports_tools(self, *a, **k):
        return False


def test_draft_extracts_clean_solidity_from_prose(tmp_path):
    client = _FakeClient(f"Looking at the errors, let me fix it:\n\n```solidity\n{_SOL}\n```\nDone.")
    code = pqr.draft(client, TASK, tmp_path, protocol_mode="marker", symbol_index=None,
                     tracer=NOOP_TRACER)
    assert code == _SOL
    assert "Looking at" not in code and "```" not in code


def _run_empty_draft(tmp_path, monkeypatch, reply=""):
    """Drive _process_finding with a draft that returns `reply` (extracted → maybe empty)."""
    monkeypatch.setattr(pqr, "draft", lambda *a, **k: pqr._extract_solidity(reply))
    monkeypatch.setattr(pqr, "run_tests", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("run_tests must not be reached when the draft has no code")))
    args = types.SimpleNamespace(project=tmp_path, test_scaffold="", no_scaffold=True,
                                 no_example=True, example_poc="", no_file_map=True,
                                 lookup_budget=0, attempts=3, image=None,
                                 no_scaffold_synthesis=False)
    events: list[dict] = []
    outcome = pqr._process_finding(
        TASK, args=args, client=object(), sandbox=object(), log=events.append,
        symbol_index=None, file_map="", protocol_mode="marker", fork_rpc=None,
        require_pass_effective=False, poc_dir=tmp_path / "audit" / "poc", tracer=NOOP_TRACER)
    return outcome, [e["event"] for e in events]


def test_prose_only_draft_fails_without_writing(tmp_path, monkeypatch):
    outcome, names = _run_empty_draft(tmp_path, monkeypatch,
                                      reply="Let me analyze what went wrong before.")
    assert outcome == "draft_failed"
    assert "written" not in names                             # no PoC file written
    assert list((tmp_path / "audit" / "poc").glob("*.sol")) == []  # no .sol on disk

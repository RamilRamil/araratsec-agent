"""Feature 014 US3 / SC-001: automatic, deduplicated, non-blocking lesson capture.

Drives `_process_finding` (spec-009 offline fake model + fake sandbox) through a run where
attempt 1 is stuck on a compile signature and attempt 2 resolves it, and asserts exactly
one deduplicated candidate is emitted — with no model, Docker, or network.
"""
from __future__ import annotations

import types
from pathlib import Path

import scripts.poc_queue_runner as pqr
from sr_agent.eval.tracer import NOOP_TRACER
from sr_agent.memory.lessons import LessonStore
from audit_agent.tools.write_execute import TestResult as _ForgeResult

SECRET = b"\x00" * 32
TASK = {"id": "X-01", "title": "example finding", "location": "", "description": "a bug"}
REAL = "contract PoC is Base { function test_x() public { assertEq(cdo.coverage(), 1); } }"
_PASS = _ForgeResult(passed=True, exit_code=0, stdout="Ran 1 test for X\n[PASS] test_x()", stderr="")
_COMPILE_ERR = _ForgeResult(
    passed=False, exit_code=1,
    stdout="Compiler run failed:\nError (7576): Undeclared identifier.", stderr="")


def _args(project: Path, attempts: int = 3) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        project=project, test_scaffold="", no_scaffold=True, no_example=True,
        example_poc="", no_file_map=True, lookup_budget=0, attempts=attempts, image=None,
        no_scaffold_synthesis=False)


def _run(project, *, drafts, fixes, results, store, monkeypatch, attempts=3):
    draft_q, fix_q, result_q = list(drafts), list(fixes), list(results)
    monkeypatch.setattr(pqr, "draft", lambda *a, **k: draft_q.pop(0))
    monkeypatch.setattr(pqr, "fix", lambda *a, **k: fix_q.pop(0))
    monkeypatch.setattr(pqr, "run_tests", lambda *a, **k: result_q.pop(0))
    monkeypatch.setattr(pqr, "_lesson_store", lambda: store)  # wire our tmp store
    events: list[dict] = []
    outcome = pqr._process_finding(
        TASK, args=_args(project, attempts), client=object(), sandbox=object(),
        log=events.append, symbol_index=None, file_map="", protocol_mode="marker",
        fork_rpc=None, require_pass_effective=False, poc_dir=project / "audit" / "poc",
        tracer=NOOP_TRACER)
    return outcome, [e["event"] for e in events]


def _store(tmp_path: Path) -> LessonStore:
    return LessonStore(tmp_path / "lessons", tmp_path / "knowledge", SECRET)


def test_resolved_signature_emits_one_candidate(tmp_path, monkeypatch):
    store = _store(tmp_path)
    outcome, names = _run(tmp_path, drafts=[REAL], fixes=[REAL],
                          results=[_COMPILE_ERR, _PASS], store=store, monkeypatch=monkeypatch)
    assert outcome == "passed_unchecked"  # feature 025: no fix -> honest unchecked
    assert names.count("lesson_captured") == 1
    pending = store.list_pending()
    assert len(pending) == 1
    c = pending[0]
    assert c.category == "poc-compile"
    assert c.provenance["origin"] == "llm_inference"
    assert c.trigger_signature == ["Undeclared identifier."]


def test_identical_resolution_is_deduped_across_runs(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _run(tmp_path, drafts=[REAL], fixes=[REAL], results=[_COMPILE_ERR, _PASS],
         store=store, monkeypatch=monkeypatch)
    # a second finding hits + resolves the SAME signature → no new candidate (SC-001)
    outcome, names = _run(tmp_path, drafts=[REAL], fixes=[REAL],
                          results=[_COMPILE_ERR, _PASS], store=store, monkeypatch=monkeypatch)
    assert outcome == "passed_unchecked"  # feature 025: no fix -> honest unchecked
    assert names.count("lesson_captured") == 0
    assert len(store.list_pending()) == 1


def test_capture_failure_does_not_abort_the_run(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def _boom(*a, **k):
        raise OSError("queue unwritable")

    monkeypatch.setattr(store, "capture", _boom)
    outcome, names = _run(tmp_path, drafts=[REAL], fixes=[REAL],
                          results=[_COMPILE_ERR, _PASS], store=store, monkeypatch=monkeypatch)
    assert outcome == "passed_unchecked"            # feature 025; run completes despite capture failing
    assert "lesson_capture_error" in names          # the failure was swallowed + logged

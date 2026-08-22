"""Feature 009 US2: the PoC-workability harness's per-finding orchestration loop,
driven end-to-end OFFLINE - no Ollama, no Docker, no network.

`_process_finding` (extracted from `main()`'s loop body, contracts/
process-finding.md) is driven through a scripted fake model (monkeypatched
`draft`/`fix`) and a fake sandbox (monkeypatched `run_tests` returning scripted
`TestResult`s). Each scenario asserts BOTH the recorded `outcome` and the key
events emitted - so a regression in the loop's control flow or its outcome
classification is caught locally in seconds, not only in a metered GPU run (every
bug this class surfaced in this session's live runs would have been caught here).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

import scripts.poc_queue_runner as pqr
from audit_agent.proof.solidity_index import SymbolIndex
from sr_agent.eval.tracer import NOOP_TRACER
from audit_agent.tools.write_execute import TestResult as _ForgeResult


def _args(project: Path, attempts: int = 3) -> types.SimpleNamespace:
    """A minimal argparse-like namespace: scaffold/example/file-map all disabled
    so the loop's grounding calls are no-ops and the test stays offline and
    focused on the draft→run→fix→classify control flow."""
    return types.SimpleNamespace(
        project=project, test_scaffold="", no_scaffold=True, no_example=True,
        example_poc="", no_file_map=True, lookup_budget=0, attempts=attempts, image=None,
        no_scaffold_synthesis=False,
    )


def _run(task, project, *, drafts, fixes, results, attempts=3, monkeypatch,
         require_pass=False):
    """Drive one finding through `_process_finding` with scripted model + sandbox.
    Returns (outcome, events)."""
    draft_q = list(drafts)
    fix_q = list(fixes)
    result_q = list(results)
    monkeypatch.setattr(pqr, "draft", lambda *a, **k: draft_q.pop(0))
    monkeypatch.setattr(pqr, "fix", lambda *a, **k: fix_q.pop(0))
    monkeypatch.setattr(pqr, "run_tests", lambda *a, **k: result_q.pop(0))

    events: list[dict] = []
    outcome = pqr._process_finding(
        task, args=_args(project, attempts), client=object(), sandbox=object(),
        log=events.append, symbol_index=None, file_map="", protocol_mode="marker",
        fork_rpc=None, require_pass_effective=require_pass, poc_dir=project / "audit" / "poc",
        tracer=NOOP_TRACER,
    )
    return outcome, events


def _evnames(events):
    return [e["event"] for e in events]


TASK = {"id": "X-01", "title": "example finding", "location": "", "description": "a bug"}

# A structurally-real PoC (has an assertion) vs. a vacuous one (no assertion).
REAL = "contract PoC is Base { function test_x() public { assertEq(cdo.coverage(), 1); } }"
VACUOUS = "contract PoC is Base { function test_x() public { /* nothing */ } }"

_PASS = _ForgeResult(passed=True, exit_code=0, stdout="Ran 1 test for X\n[PASS] test_x()", stderr="")
_VACUOUS_PASS = _ForgeResult(passed=True, exit_code=0, stdout="Ran 1 test for X\n[PASS] test_x()", stderr="")
_COMPILE_ERR = _ForgeResult(passed=False, exit_code=1,
                          stdout="Compiler run failed:\nError (7576): Undeclared identifier.", stderr="")


def test_loop_clean_pass(tmp_path, monkeypatch):
    """First draft is structurally real and the run passes → outcome 'passed'."""
    outcome, events = _run(TASK, tmp_path, drafts=[REAL], fixes=[], results=[_PASS], monkeypatch=monkeypatch)
    # feature 025: TASK carries no fix, so falsification cannot run -> passed_unchecked (honest),
    # not the old bare "passed" that hid whether verification happened.
    assert outcome == "passed_unchecked"
    names = _evnames(events)
    assert names[0] == "task_start"
    assert "tested" in names
    assert events[-1]["event"] == "task_done" and events[-1]["outcome"] == "passed_unchecked"
    assert events[-1]["verify_reason"] == "no_fix"


def test_loop_vacuous_pass_rejected(tmp_path, monkeypatch):
    """A run that passes but whose PoC is vacuous (no assertion) is NOT a success -
    every attempt is rejected and the finding ends 'vacuous_pass'."""
    outcome, events = _run(
        TASK, tmp_path, drafts=[VACUOUS], fixes=[VACUOUS], results=[_VACUOUS_PASS, _VACUOUS_PASS],
        attempts=2, monkeypatch=monkeypatch,
    )
    assert outcome == "vacuous_pass"
    assert "rejected_vacuous" in _evnames(events)
    assert events[-1]["outcome"] == "vacuous_pass"


def test_loop_compile_error_then_repair(tmp_path, monkeypatch):
    """A draft with a compile error, corrected by the next fix → a repair round runs
    and the corrected attempt reaches 'passed'."""
    outcome, events = _run(
        TASK, tmp_path, drafts=[REAL], fixes=[REAL], results=[_COMPILE_ERR, _PASS],
        attempts=3, monkeypatch=monkeypatch,
    )
    assert outcome == "passed_unchecked"  # feature 025: no fix in TASK -> honest unchecked
    names = _evnames(events)
    assert names.count("written") == 2  # two attempts written
    assert names.count("tested") == 2


def test_loop_revert_hints_carries_trace(tmp_path, monkeypatch):
    """Feature 029 (US3/FR-008): a compiled-but-failed attempt whose forge stdout carries a -vvv
    trace produces a `revert_hints` event marked `with_trace` and containing the trace. Needs
    require_pass so a compiled attempt is not accepted before the exploit actually triggers.
    SYNTHETIC trace, invented names - no target material."""
    trace_stdout = (
        "Ran 2 tests for test/Exploit.t.sol:ExploitTest\n"
        "[FAIL: gate blocks the caller] testExploit() (gas: 8772)\n"
        "Traces:\n  [8772] ExploitTest::testExploit()\n"
        "    ├─ [549] DemoVault::gate() [staticcall]\n"
        "    │   └─ ← [Revert] gate blocks the caller\n"
        "    └─ ← [Revert] gate blocks the caller\n\n"
        "Backtrace:\n  at DemoVault.gate\n\n"
        "[PASS] testSetup() (gas: 7746)\n"
        "Suite result: FAILED. 1 passed; 1 failed; 0 skipped\n")
    reverted = _ForgeResult(passed=False, exit_code=1, stdout=trace_stdout, stderr="")
    outcome, events = _run(
        TASK, tmp_path, drafts=[REAL], fixes=[REAL],
        results=[reverted, _PASS], attempts=2, require_pass=True, monkeypatch=monkeypatch)
    rh = [e for e in events if e["event"] == "revert_hints"]
    assert rh, "a compiled-but-failed attempt must emit a revert_hints event"
    assert rh[0]["with_trace"] is True
    assert "EXECUTION TRACE" in rh[0]["hints"] and "DemoVault::gate()" in rh[0]["hints"]


def test_loop_deterministic_9553_fix_no_model_no_attempt(tmp_path, monkeypatch):
    """Feature 032: an attempt that fails to compile with a 9553 is repaired IN-PLACE by the harness
    (address_interface transform), recompiled, and accepted - WITHOUT calling the model `fix()` and
    WITHOUT consuming a model attempt (SC-008). Invented names - no target material."""
    draft = "contract PoC is Base { function t() public { reg.cfg(address(thing)); assertEq(a, 1); } }"
    fail_9553 = _ForgeResult(passed=False, exit_code=1, stdout=(
        "Compiler run failed:\nError (9553): Invalid implicit conversion from address to contract "
        "IThing requested.\n  --> audit/poc/1.t.sol:1:46:\n"), stderr="")
    ok = _ForgeResult(passed=True, exit_code=0, stdout="Ran 1 test\n[PASS] t()", stderr="")
    # fixes=[] → the model fix() must NOT be called (it would IndexError on the empty queue)
    outcome, events = _run(TASK, tmp_path, drafts=[draft], fixes=[],
                           results=[fail_9553, ok], attempts=3, monkeypatch=monkeypatch)
    det = [e for e in events if e["event"] == "deterministic_fix"]
    assert det and det[0]["fixes"] == ["address_interface"]          # harness fixed 9553 itself
    tested = [e for e in events if e["event"] == "tested"]
    assert len(tested) == 1 and tested[0]["compiled"] is True        # one attempt, now compiles
    assert not any(e["event"] == "written" and e["attempt"] == 2 for e in events)  # no attempt consumed


def test_loop_stall_exhausts(tmp_path, monkeypatch):
    """Every attempt returns the identical compile error → a stall is detected and
    the finding ends 'exhausted'."""
    outcome, events = _run(
        TASK, tmp_path, drafts=[REAL], fixes=[REAL, REAL],
        results=[_COMPILE_ERR, _COMPILE_ERR, _COMPILE_ERR], attempts=3, monkeypatch=monkeypatch,
    )
    assert outcome == "exhausted"
    assert "stall_detected" in _evnames(events)
    assert events[-1]["outcome"] == "exhausted"


def test_loop_budget_stop(tmp_path, monkeypatch):
    """main()'s wall-clock guard: once the budget is exceeded, the loop stops
    without processing the next finding. Driven through main() with the pre-loop
    seams faked; a scripted monotonic clock trips the budget on the 2nd finding."""
    processed: list[str] = []
    monkeypatch.setattr(pqr, "_process_finding", lambda task, **k: processed.append(task["id"]))

    # scripted monotonic: run_start=0, finding-1 check=0 (under budget),
    # finding-2 check=100s (100/60 > 1 min budget → break).
    clock = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(pqr.time, "monotonic", lambda: next(clock))

    fake_tasks = [{"id": "A-01", "title": "a", "location": "", "description": "d"},
                  {"id": "A-02", "title": "b", "location": "", "description": "d"}]
    monkeypatch.setattr(pqr, "extract_tasks", lambda *a, **k: fake_tasks)
    monkeypatch.setattr(pqr, "build_file_manifest", lambda *a, **k: "")
    monkeypatch.setattr(pqr, "DockerSandbox", lambda *a, **k: object())

    class _FakeClient:
        model = "fake"
        def __init__(self, *a, **k): pass
        def warm(self, *a, **k): return True
        def ready(self, *a, **k): return True
        def available(self, *a, **k): return True
        def supports_tools(self, *a, **k): return False
    monkeypatch.setattr(pqr, "LocalClient", _FakeClient)

    monkeypatch.setattr(pqr, "Tracer", lambda *a, **k: NOOP_TRACER)

    report = tmp_path / "report.md"
    report.write_text("# report", encoding="utf-8")
    monkeypatch.setenv("POC_PROJECT", str(tmp_path))
    monkeypatch.setenv("POC_REPORT", str(report))
    # --provider local: this test drives the loop through the monkeypatched _FakeClient
    # (LocalClient), independent of main()'s default provider (now gemini, which would abort
    # on a missing key before the loop).
    monkeypatch.setattr("sys.argv", ["poc_queue_runner.py", "--provider", "local",
                                     "--no-symbol-index",
                                     "--attempts", "1", "--max-minutes", "1"])

    pqr.main()

    # only the first finding was processed before the budget tripped on the second.
    assert processed == ["A-01"]


# ── Feature 028: --tasks-from PINS a supplied task list (bypasses model extraction) ──

def _drive_main(tmp_path, monkeypatch, extra_argv, *, extract_stub):
    """Drive main() through its pre-loop seams (like test_loop_budget_stop), stubbing the prove loop.
    Returns the emitted events (read from the progress jsonl). `extract_stub` replaces extract_tasks."""
    monkeypatch.setattr(pqr, "_process_finding", lambda task, **k: None)
    monkeypatch.setattr(pqr, "extract_tasks", extract_stub)
    monkeypatch.setattr(pqr, "build_file_manifest", lambda *a, **k: "")
    monkeypatch.setattr(pqr, "DockerSandbox", lambda *a, **k: object())
    monkeypatch.setattr(pqr, "_harness_sandbox", lambda *a, **k: object())

    class _FakeClient:
        model = "fake"
        def __init__(self, *a, **k): pass
        def warm(self, *a, **k): return True
        def ready(self, *a, **k): return True
        def available(self, *a, **k): return True
        def supports_tools(self, *a, **k): return False
    monkeypatch.setattr(pqr, "LocalClient", _FakeClient)
    monkeypatch.setattr(pqr, "Tracer", lambda *a, **k: NOOP_TRACER)

    report = tmp_path / "report.md"; report.write_text("# report", encoding="utf-8")
    monkeypatch.setenv("POC_PROJECT", str(tmp_path))
    monkeypatch.setenv("POC_REPORT", str(report))
    # --provider local: drive the loop via the monkeypatched _FakeClient, independent of the
    # default provider (now gemini, which aborts pre-loop on a missing key).
    monkeypatch.setattr("sys.argv", ["poc_queue_runner.py", "--provider", "local",
                                     "--no-symbol-index",
                                     "--attempts", "1"] + extra_argv)
    pqr.main()
    log = tmp_path / "audit" / "poc" / "_runner_progress.jsonl"
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


def test_tasks_from_bypasses_model_extraction(tmp_path, monkeypatch):
    """FR-001/FR-005/FR-006-inverse: with --tasks-from, extract_tasks is NEVER called (stub raises),
    the run still succeeds, and an `extracted` event fires with the file's ids."""
    tf = tmp_path / "tasks.json"
    tf.write_text('[{"id":"7","title":"Pinned finding","location":"L","description":"d"}]', encoding="utf-8")

    def _boom(*a, **k):
        raise AssertionError("extract_tasks must NOT be called when --tasks-from is set")

    events = _drive_main(tmp_path, monkeypatch, ["--tasks-from", str(tf)], extract_stub=_boom)
    extracted = [e for e in events if e.get("event") == "extracted"]
    assert extracted and extracted[0]["ids"] == ["7"]        # the file's id, not a model's


def test_default_still_extracts_with_model(tmp_path, monkeypatch):
    """FR-006: WITHOUT --tasks-from the default path is unchanged - extract_tasks IS consulted."""
    called = {"n": 0}

    def _extract(*a, **k):
        called["n"] += 1
        return [{"id": "M-01", "title": "from model", "location": "", "description": "d",
                 "fix": None, "fix_patch": None}]

    events = _drive_main(tmp_path, monkeypatch, [], extract_stub=_extract)
    assert called["n"] == 1                                   # the model extractor was used
    assert any(e.get("event") == "extracted" and e["ids"] == ["M-01"] for e in events)


def test_tasks_from_malformed_aborts_cleanly(tmp_path, monkeypatch):
    """A1/FR-011: a malformed --tasks-from file aborts as a logged `extract_failed` + SystemExit -
    NOT a raw traceback (the branch is inside main()'s existing try/except)."""
    tf = tmp_path / "bad.json"; tf.write_text("{ not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        _drive_main(tmp_path, monkeypatch, ["--tasks-from", str(tf)],
                    extract_stub=lambda *a, **k: [])
    log = tmp_path / "audit" / "poc" / "_runner_progress.jsonl"
    events = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    assert any(e.get("event") == "extract_failed" for e in events)


# ── Feature 010 + 025: mutation-verify wiring into the real_pass branch ─────
# mutation_verify's internals (extract/apply/classify) are unit-tested in
# test_poc_queue_runner.py; here we test that the LOOP consults it exactly on a
# genuine PASS and maps its (status, reason) verdict to the reported outcome.
# Feature 025 split the outcome so "verified" and "could not check" stop reading
# the same: verified -> passed_verified; unavailable(reason) -> passed_unchecked
# carrying the reason; unverified_pass (proof survived the fix) -> unchanged.

def _run_with_mutverify(task, project, *, results, verdict, monkeypatch, attempts=2):
    # `verdict` is the (status, reason) tuple mutation_verify now returns (feature 025).
    result_q = list(results)
    monkeypatch.setattr(pqr, "draft", lambda *a, **k: REAL)
    monkeypatch.setattr(pqr, "fix", lambda *a, **k: REAL)
    monkeypatch.setattr(pqr, "run_tests", lambda *a, **k: result_q.pop(0))
    calls = {"n": 0}
    def _fake_mutverify(*a, **k):
        calls["n"] += 1
        return verdict
    monkeypatch.setattr(pqr, "mutation_verify", _fake_mutverify)
    events = []
    outcome = pqr._process_finding(
        task, args=_args(project, attempts), client=object(), sandbox=object(),
        log=events.append, symbol_index=None, file_map="", protocol_mode="marker",
        fork_rpc=None, require_pass_effective=False, poc_dir=project / "audit" / "poc",
        tracer=NOOP_TRACER,
    )
    return outcome, events, calls["n"]


def test_loop_mutation_verified_marks_passed_verified(tmp_path, monkeypatch):
    """US1 scenario 1: a genuine PASS whose PoC then FAILS on the applied fix is
    `passed_verified` - falsification ran and the proof depends on the bug."""
    task = {"id": "H-01", "title": "silo padding", "location": "", "description": "d", "fix": "DIFF"}
    outcome, events, n = _run_with_mutverify(
        task, tmp_path, results=[_PASS], verdict=("verified", ""), monkeypatch=monkeypatch)
    assert outcome == "passed_verified"
    assert n == 1  # consulted exactly once, on the pass


def test_loop_mutation_unverified_downgrades(tmp_path, monkeypatch):
    """US1 scenario 3: the 2026-07-06 false-positive class - a PASS that STILL passes
    on the fix stays `unverified_pass`, string and behavior unchanged (FR-003)."""
    task = {"id": "H-01", "title": "silo padding", "location": "", "description": "d", "fix": "DIFF"}
    outcome, events, n = _run_with_mutverify(
        task, tmp_path, results=[_PASS], verdict=("unverified_pass", ""), monkeypatch=monkeypatch)
    assert outcome == "unverified_pass"
    assert events[-1]["outcome"] == "unverified_pass"


@pytest.mark.parametrize("reason",
                         ["no_fix", "reconstruction_refused", "patch_failed", "patched_no_build", "infra"])
def test_loop_mutation_unavailable_marks_unchecked_with_reason(tmp_path, monkeypatch, reason):
    """US1 scenario 2 + 4 (FR-002, FR-009, SC-006): every inability-to-verify reason yields
    `passed_unchecked` carrying that reason - never a failure, never a false downgrade."""
    task = {"id": "H-01", "title": "silo padding", "location": "", "description": "d", "fix": None}
    outcome, events, n = _run_with_mutverify(
        task, tmp_path, results=[_PASS], verdict=("unavailable", reason), monkeypatch=monkeypatch)
    assert outcome == "passed_unchecked"
    assert events[-1]["outcome"] == "passed_unchecked"
    assert events[-1]["verify_reason"] == reason


def test_loop_passed_variants_are_not_quarantined(tmp_path, monkeypatch):
    """US1 trap test (research Decision 2): the quarantine gate keyed on the literal `"passed"`,
    so the outcome split must update it or every successful PoC lands in poc_failed/. Both
    passed_verified and passed_unchecked stay OUT; unverified_pass stays IN."""
    task = {"id": "H-01", "title": "t", "location": "", "description": "d", "fix": "DIFF"}
    for verdict, expect in [(("verified", ""), "passed_verified"),
                            (("unavailable", "no_fix"), "passed_unchecked")]:
        outcome, events, _ = _run_with_mutverify(
            task, tmp_path, results=[_PASS], verdict=verdict, monkeypatch=monkeypatch)
        assert outcome == expect
        assert not any(e["event"] == "quarantined" for e in events)
    # a proof that survives its own fix proves nothing → it IS quarantined
    outcome, events, _ = _run_with_mutverify(
        task, tmp_path, results=[_PASS], verdict=("unverified_pass", ""), monkeypatch=monkeypatch)
    assert outcome == "unverified_pass"
    assert any(e["event"] == "quarantined" for e in events)


def test_loop_mutation_not_consulted_on_non_pass(tmp_path, monkeypatch):
    """mutation_verify runs ONLY on a genuine pass (FR-007) - a stall/exhausted
    finding never consults it."""
    task = {"id": "H-01", "title": "t", "location": "", "description": "d", "fix": "DIFF"}
    _, _, n = _run_with_mutverify(
        task, tmp_path, results=[_COMPILE_ERR, _COMPILE_ERR], verdict=("verified", ""),
        monkeypatch=monkeypatch, attempts=2)
    assert n == 0  # never consulted - the finding never passed


# ── Feature 011: scaffold synthesis wiring into _process_finding ────────────
# synthesize_scaffold's internals are unit-tested; here we test that the loop
# consults it exactly on detected insufficiency and swaps the scaffold on success,
# falls back on failure, and never consults it when the scaffold is sufficient.

def _run_synth(task, project, *, missing, synth_returns, monkeypatch):
    monkeypatch.setattr(pqr, "scaffold_missing_types", lambda *a, **k: missing)
    calls = {"n": 0}
    def _fake_synth(proj, tsk, miss, existing, si, cl, sb, log, **k):
        calls["n"] += 1
        if synth_returns is None:
            log({"event": "scaffold_synthesis_failed", "finding_id": tsk["id"], "reason": "no_build"})
            return None
        # write a real base file so read_scaffold can read it back
        d = project / "audit" / "poc" / "_synth"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "SynthBase.sol"
        p.write_text("// SPDX\npragma solidity ^0.8.28;\nabstract contract SynthBase {}\n", encoding="utf-8")
        log({"event": "scaffold_synthesized", "finding_id": tsk["id"], "path": str(p.relative_to(project))})
        return p
    monkeypatch.setattr(pqr, "synthesize_scaffold", _fake_synth)
    monkeypatch.setattr(pqr, "draft", lambda *a, **k: REAL)
    monkeypatch.setattr(pqr, "run_tests", lambda *a, **k: _PASS)
    monkeypatch.setattr(pqr, "mutation_verify", lambda *a, **k: ("unavailable", "no_fix"))
    events = []
    outcome = pqr._process_finding(
        task, args=_args(project, 1), client=object(), sandbox=object(),
        log=events.append, symbol_index=None, file_map="", protocol_mode="marker",
        fork_rpc=None, require_pass_effective=False, poc_dir=project / "audit" / "poc",
        tracer=NOOP_TRACER,
    )
    return outcome, events, calls["n"]


def test_loop_synth_used_on_success(tmp_path, monkeypatch):
    """An insufficient-scaffold finding whose synthesis succeeds drafts under the
    synthesized base (a `scaffold_synthesized` grounding swap is emitted)."""
    task = {"id": "H-01", "title": "silo padding", "location": "CooldownVault", "description": "d"}
    outcome, events, n = _run_synth(task, tmp_path, missing=["CooldownVault"],
                                    synth_returns="ok", monkeypatch=monkeypatch)
    assert n == 1  # synthesis consulted on insufficiency
    assert any(e["event"] == "scaffold_synthesized" for e in events)
    assert any(e.get("stage") == "synthesized" for e in events)  # scaffold swapped


def test_loop_synth_fallback_on_failure(tmp_path, monkeypatch):
    """Feature 040 FR-011: synthesis failure does NOT fall through to draft on the
    insufficient base - Option-C ladder terminals instead (base-insufficient here:
    no symbol_index / lookup_budget=0 ⇒ lookup could not run)."""
    task = {"id": "H-01", "title": "t", "location": "CooldownVault", "description": "d"}
    outcome, events, n = _run_synth(task, tmp_path, missing=["CooldownVault"],
                                    synth_returns=None, monkeypatch=monkeypatch)
    assert n == 1
    assert any(e["event"] == "scaffold_synthesis_failed" for e in events)
    assert not any(e.get("stage") == "synthesized" for e in events)  # no swap
    assert outcome == "base-insufficient"
    assert events[-1]["event"] == "task_done"
    assert events[-1]["cause"] == "base-insufficient"
    assert events[-1]["nature"] == "harness-infra"


def test_loop_synth_skipped_when_sufficient(tmp_path, monkeypatch):
    """A finding whose scaffold is sufficient never consults synthesis (SC-003)."""
    task = {"id": "H-01", "title": "t", "location": "CooldownVault", "description": "d"}
    outcome, events, n = _run_synth(task, tmp_path, missing=[],  # sufficient
                                    synth_returns="ok", monkeypatch=monkeypatch)
    assert n == 0  # never consulted
    assert not any(e["event"] in ("scaffold_synthesized", "scaffold_synthesis_failed") for e in events)


# ── Feature 012: harness prompt management (identical-off + version recorded) ─

class _PromptSpyClient:
    """Captures the prompt text draft() feeds to generate() (marker mode)."""
    model = "fake"
    def __init__(self):
        self.prompts = []
    def generate(self, prompt, options=None):
        self.prompts.append(prompt)
        return REAL


def test_loop_prompt_identical_when_tracing_off(tmp_path):
    """FR-002/SC-001: with a disabled tracer, draft's assembled prompt equals the
    pre-feature constant-based prompt (the fallback IS the constant)."""
    spy = _PromptSpyClient()
    # the byte-exact reference: format the constants exactly as the old code did
    checklist = pqr.EXPLOIT_QUALITY_CHECKLIST
    reference = pqr.DRAFT_PROMPT.format(
        fid="H-01", title="t", location="", description="d", ident="H_01",
        source="(no contract name found in location)",
        scaffold="(no base provided - deploy the real contracts yourself; still NEVER mock them)",
        example="(none)", files="(none)", callable="(none)",
        scaffold_api="",
        exploit_quality_checklist=checklist,
    ) + pqr._LOOKUP_MARKER_SUFFIX
    task = {"id": "H-01", "title": "t", "location": "", "description": "d"}
    pqr.draft(spy, task, tmp_path, protocol_mode="marker", tracer=NOOP_TRACER)
    assert spy.prompts[-1] == reference  # byte-identical to pre-feature behavior


def test_generation_records_prompt_version(tmp_path):
    """SC-002/SC-003: a draft records prompt_provenance (name+version) in the
    generation metadata; a fallback-sourced prompt records version None."""
    class _VerTracer:
        enabled = True
        _client = None
        def __init__(self): self.gen_meta = []
        def get_prompt_versioned(self, name, fallback):
            return (fallback, 3) if name == "poc-draft" else (fallback, None)
        def trace(self, *a, **k):
            import contextlib
            return contextlib.nullcontext(None)
        def generation(self, trace, *, name, model, input, output, usage=None, metadata=None):
            self.gen_meta.append(metadata)
    tr = _VerTracer()
    spy = _PromptSpyClient()
    task = {"id": "H-01", "title": "t", "location": "", "description": "d"}
    pqr.draft(spy, task, tmp_path, protocol_mode="marker", tracer=tr)
    prov = {p["name"]: p["version"] for p in tr.gen_meta[-1]["prompt_provenance"]}
    assert prov["poc-draft"] == 3                     # fetched version recorded
    assert prov["poc-exploit-checklist"] is None      # fallback-sourced → None
    assert prov["poc-lookup-marker"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Feature spec 001 — honest handling & labeling of missing PoC scaffold prerequisites.
# Absent-base environment terminal (US1) + FR-011 pre-flight abort. Contract clauses
# C1–C10 in specs/001-missing-scaffold-honesty/contracts/absent-base-terminal.md.
# ══════════════════════════════════════════════════════════════════════════════
def _args_scaffold(project: Path, *, no_scaffold: bool, test_scaffold: str = "",
                   lookup_budget: int = 0) -> types.SimpleNamespace:
    """Like _args but lets a test choose the ablation flag / operator scaffold / budget."""
    return types.SimpleNamespace(
        project=project, test_scaffold=test_scaffold, no_scaffold=no_scaffold,
        no_example=True, example_poc="", no_file_map=True, lookup_budget=lookup_budget,
        attempts=3, image=None, no_scaffold_synthesis=False,
    )


def _process(task, project, *, args, monkeypatch, symbol_index=None, forbid_draft=True):
    """Drive _process_finding with drafting FORBIDDEN by default (asserts the absent-base
    path never reaches the model). Returns (outcome, events)."""
    if forbid_draft:
        def _no_draft(*a, **k):
            raise AssertionError("draft() must not be called on the absent-base path")
        monkeypatch.setattr(pqr, "draft", _no_draft)
    events: list[dict] = []
    outcome = pqr._process_finding(
        task, args=args, client=object(), sandbox=object(), log=events.append,
        symbol_index=symbol_index, file_map="", protocol_mode="marker", fork_rpc=None,
        require_pass_effective=False, poc_dir=project / "audit" / "poc", tracer=NOOP_TRACER)
    return outcome, events


def test_absent_base_emits_environment_terminal(tmp_path, monkeypatch):
    """C1 + C5/VR-5: no deliberate disable + nothing resolved ⇒ base-insufficient
    (harness-infra), no draft, and a scaffold_absent breadcrumb whose reason is distinct
    from the missing-type scaffold_insufficient event."""
    outcome, events = _process(TASK, tmp_path, args=_args_scaffold(tmp_path, no_scaffold=False),
                               monkeypatch=monkeypatch)
    assert outcome == "base-insufficient"
    names = _evnames(events)
    assert "scaffold_absent" in names
    assert "scaffold_insufficient" not in names            # C5: distinct event
    assert "written" not in names and "tested" not in names  # no draft attempt
    done = events[-1]
    assert done["event"] == "task_done" and done["outcome"] == "base-insufficient"
    assert done["nature"] == "harness-infra"               # excluded from model denominator
    absent = next(e for e in events if e["event"] == "scaffold_absent")
    assert "no operator scaffold" in absent["reason"]


def test_absent_base_short_circuits_before_ladder(tmp_path, monkeypatch):
    """C2 / FR-004a: even with a symbol index present and lookup_budget > 0, the absent
    base returns base-insufficient and NEVER lookup_failed — the lookup ladder must not run."""
    idx = SymbolIndex.build(tmp_path)  # a present (non-None) index
    outcome, events = _process(
        TASK, tmp_path, args=_args_scaffold(tmp_path, no_scaffold=False, lookup_budget=5),
        monkeypatch=monkeypatch, symbol_index=idx)
    assert outcome == "base-insufficient"
    assert outcome != "lookup_failed"
    assert "lookup" not in _evnames(events)                # ladder never consulted


def test_no_scaffold_ablation_stays_model_column(tmp_path, monkeypatch):
    """C3 / FR-004: deliberate --no-scaffold drafts normally (model column) and emits NO
    scaffold_absent event, despite the identical empty-scaffold state."""
    outcome, events = _run(TASK, tmp_path, drafts=[REAL], fixes=[], results=[_PASS],
                           monkeypatch=monkeypatch)  # _args → no_scaffold=True
    assert outcome != "base-insufficient"
    assert "scaffold_absent" not in _evnames(events)
    assert "tested" in _evnames(events)                    # it really drafted


def test_unresolved_operator_scaffold_aborts_preflight(tmp_path, capsys):
    """C8 / FR-011: a set-but-unresolved --test-scaffold aborts (exit 2) naming the path."""
    with pytest.raises(SystemExit) as ei:
        pqr._preflight_operator_scaffold(tmp_path, "test/DoesNotExist.sol")
    assert ei.value.code == 2
    assert "DoesNotExist.sol" in capsys.readouterr().err


def test_preflight_ok_when_resolvable_and_noop_when_empty(tmp_path):
    """C8 boundary: a resolvable path and an empty spec both pass without aborting."""
    base = tmp_path / "Base.sol"
    base.write_text("pragma solidity ^0.8.28;\ncontract Base {}", encoding="utf-8")
    pqr._preflight_operator_scaffold(tmp_path, str(base))  # no raise
    pqr._preflight_operator_scaffold(tmp_path, "")         # no raise (auto-discovery legit)


def test_preflight_and_loop_share_one_resolver(tmp_path, monkeypatch):
    """C9 / VR-7: both resolve_scaffold and the pre-flight route token resolution through
    the single _resolve_scaffold_tokens helper — pinned so a future parser change can't
    make them disagree."""
    calls: list[str] = []
    real = pqr._resolve_scaffold_tokens

    def _spy(project, spec):
        calls.append(spec)
        return real(project, spec)
    monkeypatch.setattr(pqr, "_resolve_scaffold_tokens", _spy)
    base = tmp_path / "Base.sol"
    base.write_text("pragma solidity ^0.8.28;\ncontract Base {}", encoding="utf-8")
    pqr.resolve_scaffold(tmp_path, str(base), False)
    pqr._preflight_operator_scaffold(tmp_path, str(base))
    assert calls.count(str(base)) == 2                     # both went through the one resolver


def test_poc_scaffold_env_route_aborts_preflight(tmp_path, monkeypatch):
    """C10: the POC_SCAFFOLD env var is the argparse default of --test-scaffold, so a bad
    env path aborts at the same pre-flight — exercised through main() end-to-end."""
    report = tmp_path / "report.md"
    report.write_text("# report\n", encoding="utf-8")
    monkeypatch.setenv("POC_PROJECT", str(tmp_path))
    monkeypatch.setenv("POC_REPORT", str(report))
    monkeypatch.setenv("POC_SCAFFOLD", str(tmp_path / "nope" / "Bad.sol"))
    monkeypatch.setattr(sys, "argv", ["poc_queue_runner"])
    # _process_finding must never run — the abort precedes the loop.
    monkeypatch.setattr(pqr, "_process_finding",
                        lambda *a, **k: pytest.fail("pre-flight must abort before the loop"))
    with pytest.raises(SystemExit) as ei:
        pqr.main()
    assert ei.value.code == 2


def test_lookup_failed_finding_is_model_column(tmp_path, monkeypatch):
    """SC-003 part A: a finding whose scaffold is PRESENT but missing a needed type,
    with synthesis skipped and a lookup budget, terminates as `lookup_failed` (nature
    model) — the model-column miss that MUST stay in the denominator, contrasted with the
    absent-base environment terminal."""
    td = tmp_path / pqr._foundry_test_dir(tmp_path)
    td.mkdir(parents=True, exist_ok=True)
    scaffold = td / "Base.sol"
    scaffold.write_text("pragma solidity ^0.8.28;\ncontract Base { address alice; }", encoding="utf-8")
    idx = SymbolIndex.build(tmp_path)
    task = {"id": "M-1", "title": "needs a missing type", "location": "CooldownVault.cancel",
            "description": "a bug"}
    args = _args_scaffold(tmp_path, no_scaffold=False, test_scaffold=str(scaffold), lookup_budget=1)
    args.no_scaffold_synthesis = True  # skip synth so the insufficiency ladder runs
    outcome, events = _process(task, tmp_path, args=args, monkeypatch=monkeypatch, symbol_index=idx)
    assert outcome == "lookup_failed"
    done = events[-1]
    assert done["event"] == "task_done" and done["outcome"] == "lookup_failed"
    assert done["nature"] == "model"                          # retained in the model denominator


def test_denominator_characterization(tmp_path, monkeypatch):
    """SC-003 part B (anti-Goodhart, durable): over a stream carrying BOTH terminals, the
    classifier keeps the absent-base finding OUT of the model column (harness-infra) while
    RETAINING the lookup_failed finding IN it (model). Not an old-vs-new diff."""
    import scripts.scaffold_taxonomy as tax
    absent = {"run_id": "r1", "model": "m1", "terminal": True, "level": "finding_attempt",
              "cause": "base-insufficient", "finding_id": "A-1", "event": "task_done"}
    missed = {"run_id": "r1", "model": "m1", "terminal": True, "level": "finding_attempt",
              "cause": "lookup_failed", "finding_id": "L-1", "event": "task_done"}
    out = tax.classify([absent, missed], allow_truncated=True)
    assert out["finding_counts"] == {"base-insufficient": 1, "lookup_failed": 1}
    # the absent-base finding is charged to environment, the miss to the model:
    assert out["nature_share"]["model"] > 0.0                 # lookup_failed retained
    assert out["nature_share"]["harness-infra"] > 0.0         # base-insufficient charged to env
    # and the model's share is exactly the lookup_failed one, not inflated by the env gap:
    assert out["by_model"]["m1"]["finding"] == {"base-insufficient": 1, "lookup_failed": 1}

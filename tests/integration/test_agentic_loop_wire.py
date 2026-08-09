"""Feature 036 — the minimal --agentic-loop wire in _process_finding, driven OFFLINE.

Proves the opt-in branch: the instrument owns draft + the read/observe loop (a scripted
client emits a READ then a PoC), and the UNCHANGED oracle judges the final code exactly
ONCE (effective_attempts=1, fix() never called). No Ollama, no Docker, no network.
"""
from __future__ import annotations

import types
from pathlib import Path

import scripts.poc_queue_runner as pqr
from sr_agent.eval.tracer import NOOP_TRACER
from sr_agent.tools.sandbox import SandboxTimeout
from audit_agent.tools.write_execute import TestResult as _ForgeResult

TASK = {"id": "X-01", "title": "example finding", "location": "", "description": "a bug"}
REAL = "contract PoC is Base { function test_x() public { assertEq(x(), 1); } }"

_FAIL = _ForgeResult(passed=False, exit_code=1,
                     stdout="Ran 1 test for X\n[FAIL: assertion failed: 0 != 1]", stderr="")


class FakeClient:
    def __init__(self, replies):
        self._q = list(replies)

    def generate(self, prompt, options=None):
        return self._q.pop(0) if self._q else REAL


def _args(project: Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        project=project, test_scaffold="", no_scaffold=True, no_example=True,
        example_poc="", no_file_map=True, lookup_budget=3, attempts=3, image=None,
        no_scaffold_synthesis=False,
        agentic_loop=True, loop_budget_calls=1, loop_budget_min=0, loop_spin_k=3,
    )


def test_agentic_wire_reads_then_hands_final_code_to_the_oracle_once(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "C.sol").write_text("contract C { uint256 public x = 1; }\n")
    (tmp_path / "audit" / "poc").mkdir(parents=True)

    # scripted model: first reply issues a READ; after the DATA comes back it returns the PoC.
    client = FakeClient(["READ: " + str(tmp_path / "src" / "C.sol"), REAL])
    monkeypatch.setattr(pqr, "run_tests", lambda *a, **k: _FAIL)

    events: list[dict] = []
    outcome = pqr._process_finding(
        TASK, args=_args(tmp_path), client=client, sandbox=object(),
        log=events.append, symbol_index=None, file_map="", protocol_mode="marker",
        fork_rpc=None, require_pass_effective=False, poc_dir=tmp_path / "audit" / "poc",
        tracer=NOOP_TRACER,
    )

    names = [e["event"] for e in events]
    assert "agentic_loop_done" in names                 # the instrument ran
    assert names.count("tested") == 1                    # the oracle judged the final code ONCE
    # fix() is never reached under the agentic branch (effective_attempts == 1)
    assert "stall_detected" not in names and "targeted_hints" not in names
    assert outcome  # a terminal outcome was produced by the unchanged oracle path


def test_agentic_loop_sandbox_timeout_closes_run_error_not_crash(tmp_path, monkeypatch):
    """A SandboxTimeout from the loop's OWN run_poc must close the finding as `run_error`
    (harness-infra), NOT propagate and crash the whole shard — which lost every sibling
    finding in run full23_luna_loop_c10_m18 shard1 (exit code 1 mid-L-05, L-06/L-07 never ran).
    Mirrors the non-loop attempt-loop's timeout handling (poc_queue_runner.py ~2829)."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "C.sol").write_text("contract C { uint256 public x = 1; }\n")
    (tmp_path / "audit" / "poc").mkdir(parents=True)

    # scripted model reaches the loop's run_poc (READ -> code); run_poc then times out.
    client = FakeClient(["READ: " + str(tmp_path / "src" / "C.sol"), REAL])

    def _timeout(*a, **k):
        raise SandboxTimeout("Sandbox exceeded 1200.0s")

    monkeypatch.setattr(pqr, "run_tests", _timeout)

    events: list[dict] = []
    outcome = pqr._process_finding(                       # must return, not raise
        TASK, args=_args(tmp_path), client=client, sandbox=object(),
        log=events.append, symbol_index=None, file_map="", protocol_mode="marker",
        fork_rpc=None, require_pass_effective=False, poc_dir=tmp_path / "audit" / "poc",
        tracer=NOOP_TRACER,
    )

    assert outcome == "run_error"
    ev = {e["event"]: e for e in events}
    assert "run_error" in ev, [e["event"] for e in events]
    # the finding closes with a harness-infra terminal — never charged to the model column.
    assert ev["run_error"].get("terminal") is True
    assert ev["run_error"].get("cause") == "unclassified"


def test_flag_off_uses_draft_not_the_wire(tmp_path, monkeypatch):
    # With the flag off, the wire is never entered — draft() is, exactly as before.
    (tmp_path / "audit" / "poc").mkdir(parents=True)
    called = {"wire": 0, "draft": 0}
    monkeypatch.setattr(pqr, "_run_agentic_exploit_loop", lambda **k: called.__setitem__("wire", called["wire"] + 1) or REAL)
    monkeypatch.setattr(pqr, "draft", lambda *a, **k: called.__setitem__("draft", called["draft"] + 1) or REAL)
    monkeypatch.setattr(pqr, "run_tests", lambda *a, **k: _FAIL)

    args = _args(tmp_path)
    args.agentic_loop = False
    pqr._process_finding(
        TASK, args=args, client=object(), sandbox=object(), log=[].append,
        symbol_index=None, file_map="", protocol_mode="marker", fork_rpc=None,
        require_pass_effective=False, poc_dir=tmp_path / "audit" / "poc", tracer=NOOP_TRACER,
    )
    assert called["draft"] == 1 and called["wire"] == 0

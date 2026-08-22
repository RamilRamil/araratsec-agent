"""pack/006 US1: runner CLI flags and JSONL event fields the instruments consume.

Guard independence: this test MUST stay green on the pre-move tree. It does
not import relocated library modules by path, only:
  - argparse option strings in scripts/poc_queue_runner.py
  - proof_bench / capability_screen parsers
  - a synthetic golden JSONL (no model, no network)
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import scripts.capability_screen as cs
import scripts.proof_bench as pb

_REPO = Path(__file__).resolve().parents[3]
_PQR = _REPO / "scripts" / "poc_queue_runner.py"
_GOLDEN = _REPO / "tests" / "audit" / "goldens" / "runner_interface" / "one_case.jsonl"

# contracts/runner-interface.md — flags the instruments pass.
CONTRACTED_FLAGS = frozenset({
    "--project",
    "--report",
    "--tasks-from",
    "--fix-patch",
    "--provider",
    "--model",
    "--test-scaffold",
    "--example-poc",
    "--image",
    "--fork",
    "--max-minutes",
    "--only",
    "--agentic-loop",
    "--attempts",
    "--loop-budget-calls",
    "--loop-budget-min",
})

# Event types the instruments branch on. Presence of the type name is contracted.
CONTRACTED_EVENT_TYPES = frozenset({
    "extracted",
    "only_ids_not_found",
    "written",
    "tested",
    "task_done",
    "run_error",
    "sandbox_unavailable",
    "timeout",
})

# Fields read per event type (union of proof_bench + capability_screen).
CONTRACTED_FIELDS: dict[str, frozenset[str]] = {
    "extracted": frozenset({"event", "ids"}),
    "tested": frozenset({
        "event", "finding_id", "compiled", "real_pass",
        "exit_code", "stderr_tail", "stdout_tail",
    }),
    "task_done": frozenset({
        "event", "finding_id", "outcome", "verify_reason", "elapsed_s",
    }),
    "written": frozenset({"event"}),
}


def _option_strings(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.startswith("--"):
                    found.add(arg.value)
    return found


def _load_events(text: str) -> list[dict]:
    events: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def contracted_fields_present(events: list[dict]) -> bool:
    """False when a contracted field is missing or an event type is renamed away."""
    seen_types = {str(e.get("event", "")) for e in events}
    if "task_done" not in seen_types or "tested" not in seen_types:
        return False
    if "extracted" not in seen_types or "written" not in seen_types:
        return False
    for ev in events:
        etype = str(ev.get("event", ""))
        required = CONTRACTED_FIELDS.get(etype)
        if required is None:
            continue
        if not required.issubset(ev.keys()):
            return False
    return True


def test_runner_argparse_still_offers_contracted_flags() -> None:
    offered = _option_strings(_PQR)
    missing = sorted(CONTRACTED_FLAGS - offered)
    assert missing == [], f"runner dropped contracted flag(s): {missing}"


def test_golden_parses_to_verified_and_screen_signals() -> None:
    raw = _GOLDEN.read_text(encoding="utf-8")
    events = _load_events(raw)
    assert contracted_fields_present(events)
    assert pb._stage_of(events, "H-01") == "verified"
    parsed = cs.parse_runner_events(raw, "H-01")
    assert parsed["has_task_done"] is True
    assert parsed["outcome"] == "passed_verified"
    assert parsed["saw_tested"] is True
    assert parsed["elapsed_s"] == 1.5
    assert parsed["run_id"] == "run-synthetic"
    result = cs.signals_to_result(parsed)
    assert result.verified is True
    assert result.triggered is True
    assert result.transient is False


def test_renaming_outcome_fails_the_contract_helper() -> None:
    raw = _GOLDEN.read_text(encoding="utf-8").replace('"outcome"', '"result"')
    events = _load_events(raw)
    assert contracted_fields_present(events) is False
    parsed = cs.parse_runner_events(raw, "H-01")
    assert parsed["outcome"] == ""
    assert cs.signals_to_result(parsed).verified is False


def test_contracted_event_type_names_still_appear_in_runner_source() -> None:
    src = _PQR.read_text(encoding="utf-8")
    missing = sorted(
        name for name in CONTRACTED_EVENT_TYPES
        if f'"{name}"' not in src and f"'{name}'" not in src
    )
    # timeout may be a subprocess condition rather than an emitted event name
    missing = [m for m in missing if m != "timeout"]
    assert missing == [], f"runner no longer names contracted event(s): {missing}"

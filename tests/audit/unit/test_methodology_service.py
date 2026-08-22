"""Pure reducer tests (T010 / T025 / T027)."""
from __future__ import annotations

import json
from pathlib import Path

from sr_agent.models.action import Action
from sr_agent.models.dispatch import MemorySnapshot, SnapshotItem

from audit_agent.finding import Finding, Severity
from audit_agent.methodology.service import AuditMethodologyService, SnapshotRejected
from audit_agent.planner.stage1 import run_stage1
from audit_agent.planner.stage3 import run_stage3

_GOLDENS = Path(__file__).resolve().parents[1] / "goldens" / "methodology"
_service = AuditMethodologyService()


def _snap(items=(), as_of=0, session_id="s1") -> MemorySnapshot:
    return MemorySnapshot(
        session_id=session_id,
        as_of_sequence=as_of,
        measured_bytes=0,
        items=tuple(items),
    )


def test_project_is_callable_without_episodic_memory():
    projection = _service.project(_snap())
    assert projection.as_of_sequence == 0
    assert projection.targets == ()


def test_future_watermark_is_rejected():
    item = SnapshotItem(
        record_id="r1",
        log_sequence=5,
        kind="finding",
        source_type="tool_output",
        timestamp="0",
        body={"finding_id": "F1", "location": "A.sol:1", "function_name": "f", "severity": "low"},
    )
    try:
        _service.project(_snap([item], as_of=1))
    except SnapshotRejected:
        return
    raise AssertionError("expected SnapshotRejected")


def test_discovery_matches_stage1_golden(tmp_path):
    golden = json.loads((_GOLDENS / "stage1.json").read_text(encoding="utf-8"))
    (tmp_path / "A.sol").write_text(
        "contract A {\n"
        "  function safe() public view returns (uint) { return 1; }\n"
        "  function risky() public { selfdestruct(payable(msg.sender)); }\n"
        "  function iface() external;\n"
        "}\n"
    )
    report = run_stage1(tmp_path)
    assert report.priority_targets == golden["priority_targets"]
    assert report.skipped_targets == golden["skipped_targets"]
    assert report.notes == golden["notes"]
    transition = _service.apply(
        _snap(),
        Action(action_type="run_discovery", params={}),
        report=report,
        chunk_id="ab" * 32,
    )
    assert tuple(transition.stage_event.targets) == tuple(golden["priority_targets"])


def test_synthesis_matches_stage3_golden():
    golden = json.loads((_GOLDENS / "stage3.json").read_text(encoding="utf-8"))
    a = Finding(finding_id="A-1", location="Vault.sol:10", function_name="f", severity=Severity.high)
    b = Finding(finding_id="B-1", location="Vault.sol:20", function_name="f", severity=Severity.high)
    live = run_stage3([a, b])
    assert [f.model_dump(mode="json") for f in live.findings] == golden["findings"]
    items = [
        SnapshotItem(
            record_id=f.finding_id,
            log_sequence=i + 1,
            kind="finding",
            source_type="tool_output",
            timestamp="0",
            body=Finding(
                finding_id=f.finding_id,
                location=f.location,
                function_name="f",
                severity=Severity.high,
            ).model_dump(mode="json"),
        )
        for i, f in enumerate((a, b))
    ]
    # Re-create uncorrected findings for apply
    a2 = Finding(finding_id="A-1", location="Vault.sol:10", function_name="f", severity=Severity.high)
    b2 = Finding(finding_id="B-1", location="Vault.sol:20", function_name="f", severity=Severity.high)
    items = [
        SnapshotItem(
            record_id=fid,
            log_sequence=i + 1,
            kind="finding",
            source_type="tool_output",
            timestamp="0",
            body=Finding(
                finding_id=fid, location=loc, function_name="f", severity=Severity.high,
            ).model_dump(mode="json"),
        )
        for i, (fid, loc) in enumerate((("A-1", "Vault.sol:10"), ("B-1", "Vault.sol:20")))
    ]
    transition = _service.apply(_snap(items, as_of=2), Action(action_type="run_synthesis", params={}))
    assert transition.stage_event.outcome == "ran"
    assert [f.severity.value for f in transition.findings] == ["critical", "critical"]


def test_empty_synthesis_is_explicit():
    transition = _service.apply(_snap(), Action(action_type="run_synthesis", params={}))
    assert transition.stage_event.outcome == "empty"
    assert transition.projection.empty_label
    assert "clean" not in (transition.projection.empty_label or "").lower()

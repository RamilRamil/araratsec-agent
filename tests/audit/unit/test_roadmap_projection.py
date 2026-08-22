"""Roadmap projection matches the event log (SC-005)."""
from __future__ import annotations

from sr_agent.models.action import Action
from sr_agent.models.dispatch import MemorySnapshot, SnapshotItem

from audit_agent.methodology.service import AuditMethodologyService
from audit_agent.session import Stage1Report

_service = AuditMethodologyService()


def _commit(seq: int, bodies: list[dict]) -> SnapshotItem:
    return SnapshotItem(
        record_id=f"c{seq}",
        log_sequence=seq,
        kind="dispatch_commit",
        source_type="tool_output",
        timestamp="0",
        operation_id=f"op{seq}",
        body={"payloads": bodies},
    )


def test_projection_matches_discover_check_skip():
    discover = {
        "kind": "stage_event", "transition_type": "discover", "roadmap_revision": 0,
        "chunk_id": "aa" * 32, "target": None, "outcome": "ran", "reason": None,
        "as_of_sequence": 1, "targets": ["A.sol:risky", "A.sol:other"], "skipped_targets": [],
    }
    check = {
        "kind": "stage_event", "transition_type": "check", "roadmap_revision": 1,
        "chunk_id": None, "target": "A.sol:risky", "outcome": "ran", "reason": None,
        "as_of_sequence": 2, "targets": [], "skipped_targets": [],
    }
    skip = {
        "kind": "stage_event", "transition_type": "skip", "roadmap_revision": 2,
        "chunk_id": None, "target": "A.sol:other", "outcome": "skipped",
        "reason": "out of scope", "as_of_sequence": 3, "targets": [], "skipped_targets": [],
    }
    snap = MemorySnapshot(
        session_id="s", as_of_sequence=3, measured_bytes=0,
        items=(_commit(1, [discover]), _commit(2, [check]), _commit(3, [skip])),
    )
    at_s = _service.project(snap)
    assert at_s.as_of_sequence == 3
    by_target = {row.target: row for row in at_s.targets}
    assert by_target["A.sol:risky"].state == "analysed"
    assert by_target["A.sol:other"].state == "skipped"
    assert by_target["A.sol:other"].reason == "out of scope"

    earlier = MemorySnapshot(
        session_id="s", as_of_sequence=1, measured_bytes=0, items=(_commit(1, [discover]),),
    )
    at_one = _service.project(earlier)
    again = _service.project(earlier)
    assert at_one.model_dump() == again.model_dump()
    assert all(row.state == "pending" for row in at_one.targets)


def test_skip_keeps_target_visible():
    report = Stage1Report(priority_targets=["T.sol:f"], skipped_targets=[], notes="")
    transition = _service.apply(
        MemorySnapshot(session_id="s", as_of_sequence=0, measured_bytes=0, items=()),
        Action(action_type="skip_target", params={"target": "T.sol:f", "reason": "later"}),
        report=report,
    )
    assert any(r.state == "skipped" and r.target == "T.sol:f" for r in transition.projection.targets)

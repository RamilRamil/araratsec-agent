"""Sequential sessions of the same principal stay isolated (SC-008)."""
from __future__ import annotations

from sr_agent.models.dispatch import MemorySnapshot, SnapshotItem

from audit_agent.methodology.service import AuditMethodologyService

_service = AuditMethodologyService()


def test_projection_does_not_see_other_session_events():
    item = SnapshotItem(
        record_id="other",
        log_sequence=1,
        kind="dispatch_commit",
        source_type="tool_output",
        timestamp="0",
        body={"payloads": [{
            "kind": "stage_event", "transition_type": "skip", "roadmap_revision": 0,
            "chunk_id": None, "target": "Other.sol:f", "outcome": "skipped",
            "reason": "other session", "as_of_sequence": 1, "targets": [], "skipped_targets": [],
        }]},
    )
    mine = MemorySnapshot(session_id="s1", as_of_sequence=0, measured_bytes=0, items=())
    foreign = MemorySnapshot(session_id="s2", as_of_sequence=1, measured_bytes=0, items=(item,))
    assert _service.project(mine).targets == ()
    assert all(row.target != "Other.sol:f" for row in _service.project(mine).targets)
    assert _service.project(foreign).targets[0].target == "Other.sol:f"

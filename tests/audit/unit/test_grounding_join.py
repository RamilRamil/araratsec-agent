"""Grounding join from snapshot only (SC-007 / FR-016)."""
from __future__ import annotations

from sr_agent.models.dispatch import MemorySnapshot, SnapshotItem

from audit_agent.methodology.service import AuditMethodologyService

_service = AuditMethodologyService()


def _finding_item(fid: str, loc: str, seq: int) -> SnapshotItem:
    return SnapshotItem(
        record_id=fid,
        log_sequence=seq,
        kind="finding",
        source_type="external_llm_output",
        timestamp="0",
        body={"finding_id": fid, "location": loc, "function_name": "f", "severity": "high"},
    )


def _exec_item(fid: str, outcome: str, target: str, digest: str, seq: int) -> SnapshotItem:
    return SnapshotItem(
        record_id=f"ex-{seq}",
        log_sequence=seq,
        kind="dispatch_commit",
        source_type="tool_output",
        timestamp="0",
        operation_id="op",
        body={
            "payloads": [{
                "kind": "analyzer_execution",
                "analyzer_id": "run_slither",
                "analyzer_version": "slither-sandbox",
                "target": target,
                "target_digest": digest,
                "analyzer_outcome": outcome,
                "result_truncated": "",
                "finding_ids": [fid],
            }]
        },
    )


def _event_item(seq: int) -> SnapshotItem:
    return SnapshotItem(
        record_id=f"ev-{seq}",
        log_sequence=seq,
        kind="dispatch_commit",
        source_type="tool_output",
        timestamp="0",
        body={"payloads": [{
            "kind": "stage_event",
            "transition_type": "check",
            "roadmap_revision": 0,
            "chunk_id": None,
            "target": "Vault.sol:withdraw",
            "outcome": "ran",
            "reason": None,
            "as_of_sequence": seq,
            "targets": [],
            "skipped_targets": [],
        }]},
    )


def test_only_matching_ran_execution_grounds():
    snap = MemorySnapshot(
        session_id="s",
        as_of_sequence=4,
        measured_bytes=0,
        items=(
            _finding_item("G-1", "Vault.sol:12", 1),
            _finding_item("U-1", "Vault.sol:20", 2),
            _exec_item("G-1", "ran", "Vault.sol", "abc", 3),
            _event_item(4),
        ),
    )
    assert _service.is_grounded(snap, "G-1", target="Vault.sol", target_digest="abc")
    assert not _service.is_grounded(snap, "U-1", target="Vault.sol", target_digest="abc")
    assert not _service.is_grounded(snap, "G-1", target="Other.sol", target_digest="abc")
    did_not = MemorySnapshot(
        session_id="s", as_of_sequence=3, measured_bytes=0,
        items=(_finding_item("G-1", "Vault.sol:12", 1), _exec_item("G-1", "did_not_run", "Vault.sol", "abc", 2), _event_item(3)),
    )
    assert not _service.is_grounded(did_not, "G-1", target="Vault.sol", target_digest="abc")

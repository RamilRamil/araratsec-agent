"""Pure methodology reducer. No I/O, no EpisodicMemory (D16 / D25)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from audit_agent.finding import Finding
from audit_agent.methodology.models import (
    AnalyzerExecution,
    CanonicalParityRecord,
    MethodologyTransition,
    ProjectedFinding,
    RoadmapProjection,
    RoadmapRow,
    StageEvent,
)
from audit_agent.planner.stage3 import run_stage3

if TYPE_CHECKING:
    from sr_agent.models.action import Action
    from sr_agent.models.dispatch import MemorySnapshot, SnapshotItem


class SnapshotRejected(ValueError):
    """Snapshot is not projectable (future watermark or mixed session)."""


class AuditMethodologyService:
    """(MemorySnapshot, action) -> MethodologyTransition. Side-effect free."""

    def project(self, snapshot: "MemorySnapshot") -> RoadmapProjection:
        self._reject_bad_snapshot(snapshot)
        events, executions = self._unpack(snapshot)
        findings = self._findings(snapshot)
        grounded = self._grounding_map(findings, executions)
        rows = self._rows(events)
        projected = tuple(
            ProjectedFinding(
                finding_id=f.finding_id,
                location=f.location,
                severity=f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                tags=(f.bastet_tag.value,) if f.bastet_tag is not None else (),
                preconditions=dict(f.preconditions),
                notes="",
                grounded=grounded.get(f.finding_id, False),
                analyzer_id=next(
                    (e.analyzer_id for e in executions if f.finding_id in e.finding_ids and e.analyzer_outcome == "ran"),
                    None,
                ),
            )
            for f in findings
        )
        empty_label = None
        if any(e.transition_type == "synthesize" and e.outcome == "empty" for e in events):
            empty_label = "empty: no findings to synthesize"
        return RoadmapProjection(
            as_of_sequence=snapshot.as_of_sequence,
            targets=rows,
            findings=projected,
            empty_label=empty_label,
        )

    def apply(
        self,
        snapshot: "MemorySnapshot",
        action: "Action",
        *,
        report=None,
        executions: tuple[AnalyzerExecution, ...] = (),
        extra_findings: tuple[Finding, ...] = (),
        chunk_id: str | None = None,
        outcome: str | None = None,
        reason: str | None = None,
        gap_target: str | None = None,
    ) -> MethodologyTransition:
        self._reject_bad_snapshot(snapshot)
        at = action.action_type
        params = action.params or {}
        revision = self._revision(snapshot)
        watermark = snapshot.as_of_sequence

        if at == "run_discovery":
            cid = chunk_id or params.get("chunk_id") or "0" * 64
            priority = tuple(getattr(report, "priority_targets", ()) or ())
            skipped = tuple(getattr(report, "skipped_targets", ()) or ())
            event = StageEvent(
                transition_type="discover",
                roadmap_revision=revision,
                chunk_id=str(cid),
                outcome="ran",
                as_of_sequence=watermark,
                targets=priority,
                skipped_targets=skipped,
            )
        elif at == "run_check":
            target = str(params.get("target") or "")
            event = StageEvent(
                transition_type="check",
                roadmap_revision=revision,
                target=target,
                outcome=outcome or "ran",  # type: ignore[arg-type]
                as_of_sequence=watermark,
            )
        elif at == "skip_target":
            event = StageEvent(
                transition_type="skip",
                roadmap_revision=revision,
                target=str(params.get("target") or ""),
                outcome="skipped",
                reason=str(params.get("reason") or reason or "").strip(),
                as_of_sequence=watermark,
            )
        elif at == "run_synthesis":
            findings = self._findings(snapshot) + list(extra_findings)
            if findings:
                stage3 = run_stage3(list(findings))
                synth_findings = tuple(stage3.findings)
                ev_outcome = "ran"
            else:
                synth_findings = ()
                ev_outcome = "empty"
            event = StageEvent(
                transition_type="synthesize",
                roadmap_revision=revision,
                outcome=ev_outcome,
                as_of_sequence=watermark,
            )
            extra_findings = synth_findings
        elif at == "gap" or gap_target:
            event = StageEvent(
                transition_type="gap",
                roadmap_revision=revision,
                target=gap_target or str(params.get("target") or ""),
                outcome="did_not_run",
                reason=reason or "path is outside the bound include set",
                as_of_sequence=watermark,
            )
        else:
            raise ValueError(f"unsupported methodology action {at!r}")

        imagined = self._imagine(snapshot, event, executions)
        projection = self.project(imagined)
        if event.transition_type == "synthesize" and event.outcome == "empty":
            projection = projection.model_copy(update={"empty_label": "empty: no findings to synthesize"})
        return MethodologyTransition(
            stage_event=event,
            executions=executions,
            findings=tuple(extra_findings),
            projection=projection,
        )

    def parity(self, snapshot: "MemorySnapshot") -> list[CanonicalParityRecord]:
        projection = self.project(snapshot)
        events, executions = self._unpack(snapshot)
        records: list[CanonicalParityRecord] = []
        for event in events:
            records.append(
                CanonicalParityRecord(
                    transition_type=event.transition_type,
                    chunk_id=event.chunk_id,
                    target=event.target,
                )
            )
        for exe in executions:
            records.append(
                CanonicalParityRecord(
                    analyzer_id=exe.analyzer_id,
                    target=exe.target,
                    analyzer_outcome=exe.analyzer_outcome,
                )
            )
        for finding in projection.findings:
            records.append(
                CanonicalParityRecord(
                    target=finding.location.split(":")[0] if finding.location else None,
                    grounded=finding.grounded,
                    location=finding.location,
                    severity=finding.severity,
                    tags=finding.tags,
                    preconditions=finding.preconditions,
                    notes=finding.notes,
                    analyzer_id=finding.analyzer_id,
                )
            )
        records.sort(
            key=lambda r: (
                r.transition_type or "",
                r.chunk_id or "",
                r.target or "",
                r.analyzer_id or "",
            )
        )
        return records

    def is_grounded(
        self,
        snapshot: "MemorySnapshot",
        finding_id: str,
        *,
        target: str | None = None,
        target_digest: str | None = None,
    ) -> bool:
        self._reject_bad_snapshot(snapshot)
        _events, executions = self._unpack(snapshot)
        findings = self._findings(snapshot)
        finding = next((f for f in findings if f.finding_id == finding_id), None)
        if finding is None:
            return False
        want_target = target or finding.location.split(":")[0]
        for exe in executions:
            if finding_id not in exe.finding_ids:
                continue
            if exe.analyzer_outcome != "ran":
                continue
            if exe.target != want_target:
                continue
            if target_digest is not None and exe.target_digest != target_digest:
                continue
            return True
        return False

    def _reject_bad_snapshot(self, snapshot: "MemorySnapshot") -> None:
        if any(item.log_sequence > snapshot.as_of_sequence for item in snapshot.items):
            raise SnapshotRejected(
                f"snapshot names a future watermark: as_of_sequence="
                f"{snapshot.as_of_sequence} but an item is above it"
            )

    def _unpack(
        self, snapshot: "MemorySnapshot"
    ) -> tuple[list[StageEvent], list[AnalyzerExecution]]:
        events: list[StageEvent] = []
        executions: list[AnalyzerExecution] = []
        for item in snapshot.items:
            for body in _payload_bodies(item):
                kind = body.get("kind")
                if kind == "stage_event":
                    events.append(StageEvent.model_validate(body))
                elif kind == "analyzer_execution":
                    executions.append(AnalyzerExecution.model_validate(body))
        return events, executions

    def _findings(self, snapshot: "MemorySnapshot") -> list[Finding]:
        out: list[Finding] = []
        for item in snapshot.items:
            if item.kind == "finding" and item.body:
                try:
                    out.append(Finding.model_validate(item.body))
                except Exception:
                    continue
        return out

    def _grounding_map(
        self,
        findings: list[Finding],
        executions: list[AnalyzerExecution],
    ) -> dict[str, bool]:
        grounded: dict[str, bool] = {f.finding_id: False for f in findings}
        by_id = {f.finding_id: f for f in findings}
        for exe in executions:
            if exe.analyzer_outcome != "ran":
                continue
            for fid in exe.finding_ids:
                finding = by_id.get(fid)
                if finding is None:
                    continue
                file_rel = finding.location.split(":")[0]
                if exe.target != file_rel:
                    continue
                grounded[fid] = True
        return grounded

    def _rows(self, events: list[StageEvent]) -> tuple[RoadmapRow, ...]:
        order: list[str] = []
        state: dict[str, RoadmapRow] = {}

        def _touch(target: str, row: RoadmapRow) -> None:
            if target not in state:
                order.append(target)
            state[target] = row

        for event in events:
            if event.transition_type == "discover":
                for target in event.targets:
                    if target not in state:
                        _touch(
                            target,
                            RoadmapRow(target=target, state="pending", chunk_id=event.chunk_id),
                        )
            elif event.transition_type == "check" and event.target:
                _touch(
                    event.target,
                    RoadmapRow(target=event.target, state="analysed", chunk_id=event.chunk_id),
                )
            elif event.transition_type == "skip" and event.target:
                _touch(
                    event.target,
                    RoadmapRow(
                        target=event.target,
                        state="skipped",
                        reason=event.reason,
                        chunk_id=event.chunk_id,
                    ),
                )
            elif event.transition_type == "gap" and event.target:
                _touch(
                    event.target,
                    RoadmapRow(
                        target=event.target,
                        state="gap",
                        reason=event.reason,
                        chunk_id=event.chunk_id,
                    ),
                )
        return tuple(state[t] for t in order)

    def _revision(self, snapshot: "MemorySnapshot") -> int:
        events, _ = self._unpack(snapshot)
        return len(events)

    def _imagine(
        self,
        snapshot: "MemorySnapshot",
        event: StageEvent,
        executions: tuple[AnalyzerExecution, ...],
    ) -> "MemorySnapshot":
        from sr_agent.models.dispatch import MemorySnapshot, SnapshotItem

        seq = snapshot.as_of_sequence + 1
        bodies = [event.model_dump(mode="json")]
        bodies.extend(e.model_dump(mode="json") for e in executions)
        item = SnapshotItem(
            record_id="imagined",
            log_sequence=seq,
            kind="dispatch_commit",
            source_type="tool_output",
            timestamp="0",
            operation_id=None,
            body={"payloads": bodies},
        )
        return MemorySnapshot(
            session_id=snapshot.session_id,
            as_of_sequence=seq,
            measured_bytes=snapshot.measured_bytes,
            items=tuple(snapshot.items) + (item,),
        )


def _payload_bodies(item: "SnapshotItem") -> list[dict]:
    body = item.body or {}
    if item.kind == "dispatch_commit":
        payloads = body.get("payloads")
        if isinstance(payloads, list):
            return [p for p in payloads if isinstance(p, dict)]
        if body.get("kind"):
            return [body]
    if body.get("kind") in ("stage_event", "analyzer_execution"):
        return [body]
    return []

"""Stage 2 — per-target analysis via the relay channel (T055 + RLY4).

Deterministic for-loop over Stage 1 targets. Instead of calling a local model,
each target emits a relay request (Claude now / Codex later). The stage is
RESUMABLE: it emits all requests, then pauses; the human answers out-of-band;
`resume` ingests responses and writes findings to memory.

Idempotent across resumes: a per-session manifest tracks which requests have
been ingested, so re-running never double-writes (memory is append-only).

Provenance: ingested findings are written as source_type=external_llm_output —
relaying is transport, not authoring.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sr_agent.eval.tracer import NOOP_TRACER, Tracer
from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.session import AuditSession
from audit_agent.finding import Finding
from sr_agent.models.memory import MemoryRecord, SourceType
from sr_agent.orchestrator.relay import request_analysis
from audit_agent.relay_ingest import ingest_response

logger = logging.getLogger(__name__)

# A function that returns the analysis context (e.g. source code) for a target.
ContextProvider = Callable[[str], str]


@dataclass
class Stage2Result:
    status: str  # "paused" | "done"
    findings: list[Finding] = field(default_factory=list)  # ingested this call
    pending: list[str] = field(default_factory=list)       # request_ids awaiting response
    requested: int = 0
    ingested: int = 0

    @property
    def done(self) -> bool:
        return self.status == "done"


def _manifest_path(session_id: str, relay_dir: Path) -> Path:
    return relay_dir / "manifest" / f"{session_id}.json"


def _load_manifest(session_id: str, relay_dir: Path) -> dict[str, dict]:
    path = _manifest_path(session_id, relay_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(session_id: str, relay_dir: Path, manifest: dict[str, dict]) -> None:
    path = _manifest_path(session_id, relay_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_stage2(
    session: AuditSession,
    targets: list[str],
    memory: EpisodicMemory,
    relay_dir: Path,
    context_provider: ContextProvider,
) -> Stage2Result:
    """Emit relay requests for targets, ingest any responses, write findings.

    Returns status="paused" while any target still awaits a response, or
    status="done" once every target has been ingested. Safe to call repeatedly
    (resume) — already-ingested targets are not re-requested or re-written.
    """
    manifest = _load_manifest(session.session_id, relay_dir)
    already_requested = {entry["target"] for entry in manifest.values()}

    # 1. Emit requests for not-yet-requested targets.
    requested = 0
    for target in targets:
        if target in already_requested:
            continue
        context = context_provider(target)
        req = request_analysis(target, context, relay_dir)
        manifest[req.request_id] = {"target": target, "ingested": False}
        requested += 1
    _save_manifest(session.session_id, relay_dir, manifest)

    # 2. Ingest available responses (idempotent via the 'ingested' flag).
    findings: list[Finding] = []
    pending: list[str] = []
    ingested_count = 0

    for request_id, entry in manifest.items():
        if entry["ingested"]:
            continue
        result = ingest_response(request_id, relay_dir)
        if result.needs_resend:
            pending.append(request_id)
            continue

        for relay_finding in result.findings:
            payload = relay_finding.finding.model_dump()
            # Persist the sanitized analysis notes + any sanitize flags so the
            # report can show why the finding matters. notes is data, not a command.
            payload["notes"] = relay_finding.notes
            payload["notes_flags"] = relay_finding.notes_flags
            payload["engine"] = "model"
            record = MemoryRecord(
                project_id=session.principal.project_id,
                target=entry["target"],
                source_type=SourceType.external_llm_output,
                tool=None,
                session_id=session.session_id,
                finding=payload,
            )
            memory.write(record, principal=session.principal)
            findings.append(relay_finding.finding)
            session.finding_ids.append(relay_finding.finding.finding_id)

        entry["ingested"] = True
        ingested_count += 1

    _save_manifest(session.session_id, relay_dir, manifest)

    status = "done" if not pending else "paused"
    logger.info(
        "Stage 2 %s: requested=%d ingested=%d pending=%d",
        status, requested, ingested_count, len(pending),
    )
    return Stage2Result(
        status=status,
        findings=findings,
        pending=pending,
        requested=requested,
        ingested=ingested_count,
    )


def run_stage2_local(
    session: AuditSession,
    targets: list[str],
    memory: EpisodicMemory,
    client,
    context_provider: ContextProvider,
    tracer: Tracer = NOOP_TRACER,
) -> Stage2Result:
    """Synchronous Stage 2 via a local model (Ollama) — no relay, no pause.

    Each target is analyzed in one shot; findings are written to memory as
    external_llm_output (automation != authoring). A target whose model call
    fails is skipped, not fatal. `tracer` (default: no-op) logs each call as a
    Langfuse generation for observability; it never touches episodic memory.
    """
    from sr_agent.llm_core.local_client import ModelUnavailableError
    from audit_agent.analyze import analyze_target

    findings: list[Finding] = []
    analyzed = 0
    for target in targets:
        try:
            result = analyze_target(
                client, target, context_provider(target),
                tracer=tracer, session_id=session.session_id,
            )
        except ModelUnavailableError as e:
            logger.warning("Local Stage 2 skipped %s: %s", target, e)
            continue
        analyzed += 1
        for relay_finding in result.findings:
            payload = relay_finding.finding.model_dump()
            payload["notes"] = relay_finding.notes
            payload["notes_flags"] = relay_finding.notes_flags
            payload["engine"] = "model"
            memory.write(
                MemoryRecord(
                    project_id=session.principal.project_id,
                    target=target,
                    source_type=SourceType.external_llm_output,
                    tool=None,
                    session_id=session.session_id,
                    finding=payload,
                ),
                principal=session.principal,
            )
            findings.append(relay_finding.finding)
            session.finding_ids.append(relay_finding.finding.finding_id)

    logger.info("Stage 2 (local) done: analyzed=%d findings=%d", analyzed, len(findings))
    return Stage2Result(status="done", findings=findings, requested=analyzed, ingested=analyzed)

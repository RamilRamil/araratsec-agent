"""Stage 2 computation: emit/ingest relay or local model. No memory writes."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sr_agent.eval.tracer import NOOP_TRACER, Tracer
from sr_agent.orchestrator.relay import request_analysis, request_analysis_if_absent
from audit_agent.finding import Finding
from audit_agent.relay_ingest import ingest_response
from audit_agent.session import AuditSession

logger = logging.getLogger(__name__)

ContextProvider = Callable[[str], str]


@dataclass
class Stage2Result:
    status: str  # "paused" | "done"
    findings: list[Finding] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
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
    relay_dir: Path,
    context_provider: ContextProvider,
    operation_id: str | None = None,
) -> Stage2Result:
    """Emit relay requests and ingest responses. Does not write memory."""
    manifest = _load_manifest(session.session_id, relay_dir)
    already_requested = {entry["target"] for entry in manifest.values()}

    requested = 0
    for target in targets:
        if target in already_requested:
            continue
        context = context_provider(target)
        if operation_id:
            req = request_analysis_if_absent(target, context, relay_dir, operation_id)
        else:
            req = request_analysis(target, context, relay_dir)
        manifest[req.request_id] = {"target": target, "ingested": False}
        requested += 1
    _save_manifest(session.session_id, relay_dir, manifest)

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
    client,
    context_provider: ContextProvider,
    tracer: Tracer = NOOP_TRACER,
) -> Stage2Result:
    """Synchronous Stage 2 via a local model. Returns findings; does not write memory."""
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
            findings.append(relay_finding.finding)
            session.finding_ids.append(relay_finding.finding.finding_id)

    logger.info("Stage 2 (local) done: analyzed=%d findings=%d", analyzed, len(findings))
    return Stage2Result(status="done", findings=findings, requested=analyzed, ingested=analyzed)

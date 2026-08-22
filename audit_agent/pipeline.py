"""Batch audit driver over KernelActionExecutor (feature 004).

Chat and `sr-agent audit` share adapters + the pure reducer. This module
does not construct MemoryRecord or call memory.write. SmartGraphical is off.
A report file MAY be written after synthesis via audit_agent.report.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sr_agent.eval.tracer import NOOP_TRACER, Tracer
from sr_agent.io.progress import ProgressEvent, ProgressStream, silent
from sr_agent.models.action import Action
from sr_agent.models.chat import ChatSession
from sr_agent.models.dispatch import DispatchStatus
from sr_agent.orchestrator.chat_session import load_session, save_session
from sr_agent.orchestrator.executor import KernelActionExecutor
from sr_agent.orchestrator.scope import ContentScopePolicy, bind_scope
from sr_agent.tools.readonly import read_file

from audit_agent.methodology.include import AUDIT_INCLUDE
from audit_agent.methodology.service import AuditMethodologyService
from audit_agent.pack import AUDIT_PACK, set_relay_dir, set_snapshot_factory
from audit_agent.report import generate_report
from audit_agent.session import AuditInput, Stage1Report

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    status: str  # "paused" | "done"
    session_id: str
    pending: int = 0
    report_path: str | None = None
    findings_count: int = 0


def _pointer_path(session_id: str, runs_dir: Path) -> Path:
    return runs_dir / f"{session_id}.json"


def _save_pointer(session_id: str, project_id: str, audit_root: Path, output: str, runs_dir: Path) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    _pointer_path(session_id, runs_dir).write_text(
        json.dumps({
            "session_id": session_id,
            "project_id": project_id,
            "audit_root": str(audit_root),
            "output": output,
        }),
        encoding="utf-8",
    )


def _load_pointer(session_id: str, runs_dir: Path) -> dict:
    path = _pointer_path(session_id, runs_dir)
    if not path.exists():
        raise FileNotFoundError(f"No audit run: {session_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _context_provider(audit_root: Path):
    def provider(target: str) -> str:
        filename = target.split(":")[0]
        return read_file(audit_root / filename, audit_root)
    return provider


def _bind_factory(memory, project_id: str, session_id: str) -> None:
    set_snapshot_factory(
        lambda: memory.snapshot(project_id=project_id, session_id=session_id)
    )


def _executor(memory, audit_root: Path, relay_dir: Path) -> KernelActionExecutor:
    from sr_agent.tools.sandbox import DockerSandbox

    return KernelActionExecutor(
        memory=memory,
        scope_root=audit_root,
        pack_id=AUDIT_PACK.name,
        pack_contract_version=getattr(AUDIT_PACK, "contract_version", "1"),
        relay_dir=relay_dir,
        sandbox=DockerSandbox(),
    )


def start_audit(
    audit_input: AuditInput,
    audit_root: Path,
    memory,
    relay_dir: Path,
    runs_dir: Path,
    output: str = "audit-report.md",
    progress: ProgressStream | None = None,
    run_static: bool = True,
    stage2_provider: str = "relay",
    local_client=None,
    smartgraphical_root: str = "",
    tracer: Tracer = NOOP_TRACER,
) -> PipelineResult:
    """Run discovery, checks, and synthesis through KernelActionExecutor."""
    del run_static, local_client, smartgraphical_root, tracer  # FR-019: no SmartGraphical
    progress = progress or silent()
    audit_root = Path(audit_root).resolve()
    session = ChatSession(principal=audit_input.principal)
    policy = ContentScopePolicy(
        scope_root=audit_root,
        include=AUDIT_INCLUDE,
        runtime_state_roots=(),
    )
    bind_scope(session, policy)
    save_session(session, memory)
    _save_pointer(session.session_id, session.principal.project_id, audit_root, output, runs_dir)
    set_relay_dir(relay_dir if stage2_provider == "relay" else None)
    _bind_factory(memory, session.principal.project_id, session.session_id)
    executor = _executor(memory, audit_root, relay_dir)

    progress.emit(ProgressEvent.stage1_start)
    discovered = executor.execute(AUDIT_PACK, session, Action(action_type="run_discovery", params={}))
    progress.emit(ProgressEvent.stage1_done, discovered.body.splitlines()[0] if discovered.body else "discovery")

    return _continue(session, memory, audit_root, relay_dir, output, progress, executor)


def resume_audit(
    session_id: str,
    memory,
    relay_dir: Path,
    runs_dir: Path,
    progress: ProgressStream | None = None,
) -> PipelineResult:
    progress = progress or silent()
    pointer = _load_pointer(session_id, runs_dir)
    session = load_session(session_id, pointer["project_id"], memory)
    if session is None:
        raise FileNotFoundError(f"No audit session: {session_id}")
    audit_root = Path(pointer["audit_root"])
    set_relay_dir(relay_dir)
    _bind_factory(memory, session.principal.project_id, session.session_id)
    executor = _executor(memory, audit_root, relay_dir)
    return _continue(session, memory, audit_root, relay_dir, pointer["output"], progress, executor)


def _continue(
    session: ChatSession,
    memory,
    audit_root: Path,
    relay_dir: Path,
    output: str,
    progress: ProgressStream,
    executor: KernelActionExecutor,
) -> PipelineResult:
    snap = memory.snapshot(project_id=session.principal.project_id, session_id=session.session_id)
    projection = AuditMethodologyService().project(snap)
    pending_targets = [row.target for row in projection.targets if row.state == "pending"]
    for target in pending_targets:
        result = executor.execute(
            AUDIT_PACK, session, Action(action_type="run_check", params={"target": target}),
        )
        if result.status is DispatchStatus.pending:
            progress.emit(ProgressEvent.paused, target)
            save_session(session, memory)
            return PipelineResult(status="paused", session_id=session.session_id, pending=1)

    synthesized = executor.execute(AUDIT_PACK, session, Action(action_type="run_synthesis", params={}))
    progress.emit(ProgressEvent.stage3, synthesized.body.splitlines()[0] if synthesized.body else "synthesis")
    snap = memory.snapshot(project_id=session.principal.project_id, session_id=session.session_id)
    projection = AuditMethodologyService().project(snap)
    finding_dicts = [
        {
            "finding_id": f.finding_id,
            "location": f.location,
            "severity": f.severity,
            "notes": f.notes,
            "grounded": f.grounded,
        }
        for f in projection.findings
    ]
    stage1 = Stage1Report(
        priority_targets=[r.target for r in projection.targets],
        skipped_targets=[r.target for r in projection.targets if r.state == "skipped"],
        notes=projection.empty_label or "",
    )
    report_md = generate_report(session.principal.project_id, finding_dicts, stage1=stage1)
    Path(output).write_text(report_md, encoding="utf-8")
    progress.emit(ProgressEvent.report, output)
    save_session(session, memory)
    return PipelineResult(
        status="done",
        session_id=session.session_id,
        report_path=output,
        findings_count=len(finding_dicts),
    )

"""Executor-facing ports: analyzers, Stage 2 relay, file reads (not the reducer)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from sr_agent.models.action import Action
from sr_agent.models.dispatch import (
    DispatchPayload,
    DispatchResult,
    DispatchStatus,
    MemorySnapshot,
    PendingKind,
    PendingWait,
)
from sr_agent.orchestrator.scope import path_is_included

from audit_agent.methodology.cursor import first_uncommitted_chunk, partition_chunks
from audit_agent.methodology.include import AUDIT_INCLUDE
from audit_agent.methodology.models import AnalyzerExecution
from audit_agent.methodology.service import AuditMethodologyService
from audit_agent.planner.stage1 import run_stage1
from audit_agent.tools.static_analysis import slither_to_findings

if TYPE_CHECKING:
    from sr_agent.orchestrator.pack import PackContext

_service = AuditMethodologyService()
_snapshot_factory: Callable[[], MemorySnapshot] | None = None
_relay_dir: Path | None = None

SLITHER_VERSION = "slither-sandbox"
MYTHRL_VERSION = "mythril-sandbox"


def set_snapshot_factory(factory: Callable[[], MemorySnapshot] | None) -> None:
    global _snapshot_factory
    _snapshot_factory = factory


def set_relay_dir(path: Path | None) -> None:
    global _relay_dir
    _relay_dir = Path(path) if path is not None else None


def current_snapshot() -> MemorySnapshot:
    if _snapshot_factory is None:
        return MemorySnapshot(session_id="", as_of_sequence=0, measured_bytes=0, items=())
    return _snapshot_factory()


def _empty_snapshot() -> MemorySnapshot:
    return MemorySnapshot(session_id="", as_of_sequence=0, measured_bytes=0, items=())


def _result_from_transition(
    transition,
    ctx: "PackContext",
    *,
    pending: PendingWait | None = None,
) -> DispatchResult:
    body = ctx.wrap_data(
        "awaiting external_response" if pending is not None else _render_body(transition),
        tool=transition.stage_event.transition_type,
        path="",
    )
    if pending is not None:
        return DispatchResult(status=DispatchStatus.pending, body=body, pending=pending)
    payloads = [DispatchPayload(body=transition.stage_event.model_dump(mode="json"))]
    for exe in transition.executions:
        payloads.append(DispatchPayload(body=exe.model_dump(mode="json")))
    return DispatchResult(status=DispatchStatus.ran, body=body, payloads=payloads)


def _render_body(transition) -> str:
    event = transition.stage_event
    proj = transition.projection
    lines = [
        f"stage={event.transition_type} outcome={event.outcome}",
        f"as_of_sequence={proj.as_of_sequence}",
    ]
    if event.chunk_id:
        lines.append(f"chunk_id={event.chunk_id}")
    if event.target:
        lines.append(f"target={event.target}")
    if event.reason:
        lines.append(f"reason={event.reason}")
    if event.targets:
        lines.append("priority_targets:")
        lines.extend(f"  {t}" for t in event.targets)
    if proj.empty_label:
        lines.append(proj.empty_label)
    if proj.targets:
        lines.append("roadmap:")
        for row in proj.targets:
            extra = f" ({row.reason})" if row.reason else ""
            lines.append(f"  {row.target} [{row.state}]{extra}")
    return "\n".join(lines)


def _included_relpaths(ctx: "PackContext") -> list[str]:
    root = Path(ctx.scope_root)
    include = AUDIT_INCLUDE
    policy = getattr(ctx, "scope_policy", None)
    if policy is not None:
        include = tuple(getattr(policy, "include", include) or include)
        from sr_agent.orchestrator.scope import iter_included_files

        return [
            p.relative_to(root).as_posix()
            for p in iter_included_files(policy)
            if p.is_file()
        ]
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path_is_included(rel, include):
            out.append(rel)
    return out


def _committed_chunk_ids(snapshot: MemorySnapshot) -> list[str]:
    ids: list[str] = []
    for item in snapshot.items:
        payloads = (item.body or {}).get("payloads") if item.kind == "dispatch_commit" else None
        bodies = payloads if isinstance(payloads, list) else [item.body]
        for body in bodies:
            if isinstance(body, dict) and body.get("kind") == "stage_event":
                if body.get("transition_type") == "discover" and body.get("chunk_id"):
                    ids.append(str(body["chunk_id"]))
    return ids


def _file_of(target: str) -> str:
    return target.split(":")[0]


def _target_digest(path: Path, rel: str) -> str:
    rel_posix = rel.replace("\\", "/")
    if path.is_file():
        data = path.read_bytes()
        size = len(data)
        payload = rel_posix.encode("utf-8") + b"\0" + str(size).encode("ascii") + b"\0" + data
    else:
        payload = rel_posix.encode("utf-8") + b"\0" + b"0" + b"\0"
    return hashlib.sha256(payload).hexdigest()


def _outside_include(ctx: "PackContext", rel: str) -> bool:
    include = AUDIT_INCLUDE
    policy = getattr(ctx, "scope_policy", None)
    if policy is not None:
        include = tuple(getattr(policy, "include", include) or include)
    return not path_is_included(rel, include)


def run_discovery(action: Action, ctx: "PackContext") -> DispatchResult:
    snapshot = current_snapshot()
    relpaths = _included_relpaths(ctx)
    requested = action.params.get("chunk_id")
    if requested:
        match = next(
            ((cid, group) for cid, group in partition_chunks(relpaths) if cid == requested),
            None,
        )
        if match is None:
            return DispatchResult(
                status=DispatchStatus.error,
                body=ctx.wrap_data(f"unknown chunk_id {requested}", tool="run_discovery", path=""),
            )
        chunk_id, group = match
    else:
        nxt = first_uncommitted_chunk(relpaths, _committed_chunk_ids(snapshot))
        if nxt is None:
            chunk_id, group = (partition_chunks(relpaths) or (("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", ()),))[0]
        else:
            chunk_id, group = nxt

    root = Path(ctx.scope_root)
    focus = [root / p for p in group if (root / p).exists()]
    for rel in group:
        if _outside_include(ctx, rel):
            gap = _service.apply(
                snapshot, Action(action_type="gap", params={"target": rel}),
                gap_target=rel,
                reason="path is outside the bound include set",
            )
            return _result_from_transition(gap, ctx)

    if focus:
        report = run_stage1(root, focus=focus)
    else:
        from audit_agent.session import Stage1Report

        report = Stage1Report(priority_targets=[], skipped_targets=[], notes="No files in chunk.")
    transition = _service.apply(snapshot, action, report=report, chunk_id=chunk_id)
    return _result_from_transition(transition, ctx)


def run_check(action: Action, ctx: "PackContext") -> DispatchResult:
    snapshot = current_snapshot()
    target = str(action.params.get("target") or "")
    file_rel = _file_of(target)
    if _outside_include(ctx, file_rel):
        gap = _service.apply(
            snapshot, Action(action_type="gap", params={"target": file_rel}),
            gap_target=file_rel,
            reason="path is outside the bound include set",
        )
        return _result_from_transition(gap, ctx)

    if _relay_dir is not None and ctx.operation_id:
        pending = _maybe_relay(ctx, target)
        if pending is not None:
            return _result_from_transition(
                _service.apply(snapshot, action, outcome="ran"),
                ctx,
                pending=pending,
            )

    executions, findings, outcome = _run_analyzers(action, ctx, file_rel)
    transition = _service.apply(
        snapshot, action, executions=tuple(executions), extra_findings=tuple(findings), outcome=outcome,
    )
    return _result_from_transition(transition, ctx)


def run_synthesis(action: Action, ctx: "PackContext") -> DispatchResult:
    snapshot = current_snapshot()
    transition = _service.apply(snapshot, action)
    return _result_from_transition(transition, ctx)


def skip_target(action: Action, ctx: "PackContext") -> DispatchResult:
    reason = str(action.params.get("reason") or "").strip()
    target = str(action.params.get("target") or "").strip()
    if not target or not reason:
        return DispatchResult(
            status=DispatchStatus.error,
            body=ctx.wrap_data(
                "skip_target requires non-empty target and reason",
                tool="skip_target",
                path="",
            ),
        )
    snapshot = current_snapshot()
    transition = _service.apply(snapshot, action)
    return _result_from_transition(transition, ctx)


def _maybe_relay(ctx: "PackContext", target: str) -> PendingWait | None:
    from sr_agent.orchestrator.relay import request_analysis_if_absent
    from audit_agent.relay_ingest import ingest_response
    from sr_agent.tools.readonly import read_file

    assert _relay_dir is not None
    file_rel = _file_of(target)
    try:
        context = read_file(Path(ctx.scope_root) / file_rel, ctx.scope_root)
    except Exception:
        context = target
    request_analysis_if_absent(target, context, _relay_dir, str(ctx.operation_id))
    ingested = ingest_response(str(ctx.operation_id), _relay_dir)
    if ingested.needs_resend:
        return PendingWait(kind=PendingKind.external_response, correlation_id=str(ctx.operation_id))
    return None


def _run_analyzers(
    action: Action, ctx: "PackContext", file_rel: str
) -> tuple[list[AnalyzerExecution], list, str]:
    from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE
    from audit_agent.config import config
    from audit_agent.tools.static_analysis import MythrilError, SlitherError, run_mythril, run_slither
    from sr_agent.tools.sandbox import SandboxError, SandboxTimeout

    root = Path(ctx.scope_root)
    path = root / file_rel
    target = str(path if path.exists() else file_rel)
    digest = _target_digest(path, file_rel) if path.exists() else _target_digest(root, file_rel)
    executions: list[AnalyzerExecution] = []
    findings: list = []
    worst = "ran"

    runners = (
        ("run_slither", SLITHER_VERSION, run_slither, SlitherError),
        ("run_mythril", MYTHRL_VERSION, run_mythril, MythrilError),
    )
    for analyzer_id, version, runner, err_cls in runners:
        entry = AGENT_TOOL_SURFACE.get(analyzer_id)
        if entry is None or entry.executor is None:
            executions.append(
                AnalyzerExecution(
                    analyzer_id=analyzer_id,
                    analyzer_version=version,
                    target=file_rel,
                    target_digest=digest,
                    analyzer_outcome="did_not_run",
                    result_truncated="executor missing",
                )
            )
            worst = "did_not_run"
            continue
        if not hasattr(ctx.sandbox, "run"):
            executions.append(
                AnalyzerExecution(
                    analyzer_id=analyzer_id,
                    analyzer_version=version,
                    target=file_rel,
                    target_digest=digest,
                    analyzer_outcome="did_not_run",
                    result_truncated="sandbox has no run()",
                )
            )
            worst = "did_not_run"
            continue
        try:
            raw_findings = runner(
                target, ctx.scope_root, ctx.sandbox, timeout_s=config.chat_tool_timeout_s,
            )
            outcome = "ran"
            body = "\n".join(str(f) for f in raw_findings) or "(no findings)"
            ids: list[str] = []
            if analyzer_id == "run_slither":
                converted = slither_to_findings(raw_findings, file_rel)
                findings.extend(converted)
                ids = [f.finding_id for f in converted]
        except SandboxTimeout as exc:
            outcome, body, ids = "timeout", str(exc), []
        except (err_cls, SandboxError, KeyError) as exc:
            outcome, body, ids = "did_not_run", str(exc), []
        executions.append(
            AnalyzerExecution(
                analyzer_id=analyzer_id,
                analyzer_version=version,
                target=file_rel,
                target_digest=digest,
                analyzer_outcome=outcome,  # type: ignore[arg-type]
                result_truncated=body[:512],
                finding_ids=tuple(ids),
            )
        )
        if outcome != "ran" and worst == "ran":
            worst = outcome
    return executions, findings, worst


def _outcome_from_body(body: str) -> str:
    if "status=timeout" in body:
        return "timeout"
    if "status=did_not_run" in body or "status=unavailable" in body:
        return "did_not_run"
    if "status=error" in body:
        return "did_not_run"
    return "ran"


def _extract_json(body: str) -> str | None:
    start = body.find("{")
    end = body.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return body[start : end + 1]

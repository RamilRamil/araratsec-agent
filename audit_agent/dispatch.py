"""Audit-pack action dispatch (feature 004, R8; feature 003 lookup).

The pack callables the kernel loop delegates to: `dispatch` (read/other actions),
`execute_confirmed` (approved write_execute), and `persist_finding` (build the
domain Finding). They receive only the narrow `PackContext` — never the loop.

`persist_finding` RETURNS the Finding; it does NOT write memory. The kernel owns
the write and sets `source_type=external_llm_output` (FR-006) — a pack cannot
forge a tier (there is no memory handle in PackContext).

`dispatch` is a lookup into `AGENT_TOOL_SURFACE`. It does not construct Findings
(FR-008) and does not run write_execute tools (those go through `execute_confirmed`
after out-of-band approval).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sr_agent.guardrails.sanitize import sanitize
from sr_agent.models.chat import PoCStatusEvent
from sr_agent.tools.sandbox import SandboxError

from audit_agent.actions import AuditActionType
from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE, unavailable_payload
from audit_agent.finding import Finding, Severity
from audit_agent.tools.write_execute import run_tests, write_poc

if TYPE_CHECKING:
    from pathlib import Path

    from sr_agent.models.action import Action
    from sr_agent.orchestrator.pack import PackContext

logger = logging.getLogger(__name__)


def _poc_dir(ctx: "PackContext") -> "Path":
    """The pack-owned PoC output directory (feature 002 / D2).

    The kernel removed `poc_dir` from `PackContext`; PoC state is pack-side now.
    We derive it from the scope the kernel DOES provide — reproducing the old
    kernel default (`<scope_root>/audit/poc`) so PoC output is behavior-identical.
    """
    return ctx.scope_root / "audit" / "poc"


def dispatch(action: "Action", ctx: "PackContext") -> str:
    """Execute a validated read/other action; return DATA-wrapped output."""
    at = action.action_type
    entry = AGENT_TOOL_SURFACE.get(at)
    if entry is None:
        return ctx.wrap_data(f"TOOL ERROR: unknown action {at!r}", tool=at, path="")
    if not entry.available:
        return unavailable_payload(at, entry.missing_precondition, ctx)
    if entry.executor is None:
        return ctx.wrap_data(
            "WRITE_EXECUTE cannot run from dispatch; confirmation required",
            tool=at, path="",
        )
    return entry.executor(action, ctx)


def execute_confirmed(action: "Action", ctx: "PackContext") -> "tuple[str, PoCStatusEvent | None]":
    """Execute a write_execute action AFTER out-of-band approval (US2/R9)."""
    at = action.action_type
    finding_id = str(action.params.get("finding_id", "UNKNOWN"))

    if at == AuditActionType.write_poc:
        res = write_poc(finding_id, _poc_dir(ctx), generator=None)
        event = PoCStatusEvent(finding_id=finding_id, status="written", poc_path=str(res.path))
        return (f"PoC written to {res.path}", event)

    if at == AuditActionType.run_tests:
        test_path = action.params.get("test_path")
        try:
            result = run_tests(
                ctx.scope_root, ctx.sandbox, test_path=test_path,
                foundry_test_dir="audit/poc",  # PoCs live outside default test/ (poc-execution.md)
            )
        except SandboxError as e:
            event = PoCStatusEvent(finding_id=finding_id, status="errored", skip_reason=None)
            return (f"run_tests could not execute: {e}", event)
        # Mechanical status only — a pass means a reproduction exists, NOT a
        # confirmed/safe verdict (Constitution II).
        status = "passed" if result.passed else "failed"
        summary = f"forge test {'PASSED' if result.passed else 'FAILED'} (exit {result.exit_code})"
        return (summary, PoCStatusEvent(finding_id=finding_id, status=status))

    # Any other write_execute (e.g. deploy_test_contract) — no PoC status.
    return (dispatch(action, ctx), None)


def persist_finding(payload, ctx: "PackContext") -> "Finding | None":
    """Build and validate the domain Finding from a model-reported payload.

    Returns the Finding (or None if the payload is invalid); the KERNEL writes it
    to memory with the kernel-set source tier. The pack never touches memory.
    """
    if payload is None:
        return None
    try:
        finding = Finding(
            finding_id=payload.finding_id,
            location=payload.location,
            function_name=payload.function_name,
            severity=Severity(payload.severity),
            preconditions=payload.preconditions,
            mitigations_present=payload.mitigations_present,
        )
    except Exception as e:
        logger.warning("Invalid finding payload: %s", e)
        return None

    sanitized = sanitize(payload.notes)
    if sanitized.flags:
        logger.info("Finding notes sanitized, flags: %s", sanitized.flags)
    return finding

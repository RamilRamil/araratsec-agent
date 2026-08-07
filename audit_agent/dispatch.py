"""Audit-pack action dispatch (feature 004, R8).

The pack callables the kernel loop delegates to: `dispatch` (read/other actions),
`execute_confirmed` (approved write_execute), and `persist_finding` (build the
domain Finding). They receive only the narrow `PackContext` — never the loop.

`persist_finding` RETURNS the Finding; it does NOT write memory. The kernel owns
the write and sets `source_type=external_llm_output` (FR-006) — a pack cannot
forge a tier (there is no memory handle in PackContext).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from audit_agent.config import config
from sr_agent.guardrails.sanitize import sanitize
from sr_agent.models.action import ActionType
from sr_agent.models.chat import PoCStatusEvent
from audit_agent.finding import Finding, Severity
from audit_agent.tools.onchain import (
    OnChainError, analyze_transactions, make_alchemy_fetcher,
)
from audit_agent.tools.write_execute import run_tests, write_poc
from sr_agent.tools.readonly import ReadOnlyToolError, read_file, search_code
from sr_agent.tools.sandbox import SandboxError

if TYPE_CHECKING:
    from sr_agent.models.action import Action
    from sr_agent.orchestrator.pack import PackContext

logger = logging.getLogger(__name__)


def dispatch(action: "Action", ctx: "PackContext") -> str:
    """Execute a validated read/other action; return DATA-wrapped output."""
    at = action.action_type
    params = action.params

    try:
        if at == ActionType.read_file:
            content = read_file(params["path"], ctx.audit_root)
            return ctx.wrap_data(content, tool="read_file", path=str(params.get("path", "")))

        if at == ActionType.search_code:
            root = params.get("root", str(ctx.audit_root))
            hits = search_code(params["pattern"], root)
            body = "\n".join(f"{h.file}:{h.line}: {h.text}" for h in hits) or "(no matches)"
            return ctx.wrap_data(body, tool="search_code", path=str(root))

        if at == ActionType.analyze_transactions:
            try:
                fetcher = make_alchemy_fetcher(config.alchemy_api_key)
                res = analyze_transactions(
                    params["address"], int(params.get("from_block", 0)),
                    int(params.get("to_block", 0)), fetcher, focus=params.get("focus"),
                )
                body = "\n".join(res.notes) or "(no notable transactions)"
                return ctx.wrap_data(body, tool="analyze_transactions", path=params["address"])
            except OnChainError as e:
                return ctx.wrap_data(f"TOOL ERROR: {e}", tool="analyze_transactions", path="")
    except ReadOnlyToolError as e:
        return ctx.wrap_data(f"TOOL ERROR: {e}", tool=at.value, path="")
    except KeyError as e:
        return ctx.wrap_data(f"TOOL ERROR: missing required param {e}", tool=at.value, path="")

    # Slither/Mythril and write/execute dispatch land in later blocks.
    return ctx.wrap_data(
        f"[STUB] Tool {at.value!r} not yet implemented.",
        tool=at.value, path=str(params.get("path", "")),
    )


def execute_confirmed(action: "Action", ctx: "PackContext") -> "tuple[str, PoCStatusEvent | None]":
    """Execute a write_execute action AFTER out-of-band approval (US2/R9)."""
    at = action.action_type
    finding_id = str(action.params.get("finding_id", "UNKNOWN"))

    if at == ActionType.write_poc:
        res = write_poc(finding_id, ctx.poc_dir, generator=ctx.poc_generator)
        event = PoCStatusEvent(finding_id=finding_id, status="written", poc_path=str(res.path))
        return (f"PoC written to {res.path}", event)

    if at == ActionType.run_tests:
        test_path = action.params.get("test_path")
        try:
            result = run_tests(
                ctx.audit_root, ctx.sandbox, test_path=test_path,
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

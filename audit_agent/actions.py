"""The audit pack's DOMAIN action taxonomy (feature 002, US1).

Relocated from the kernel (`sr_agent/models/action.py`, `orchestrator/action.py`)
once the kernel opened `Action.action_type` to a free string (kernel feature 001,
Constitution III). This module owns:

  * `AuditActionType` — the domain analyzer ids ONLY. The kernel-generic ids
    (`write_memory`, `request_human_confirmation`, `escalate`, `complete`, and the
    scope-bounded reads `read_file`/`search_code`) are NOT here — they are inherited
    from the kernel (`KERNEL_GENERIC_ACTIONS ∪ pack.actions`), decisions D4/D6.
  * `ACTION_CLASS_MAP` / `REVERSIBLE` — per-id class and reversibility.
  * `_validate_params` — the domain param-validation ladder, relocated
    **behavior-preserving** from the kernel (FR-005). The ONLY change from the
    kernel original is the branch operands (`ActionType.run_slither` → the
    pack-local id); the `read_file`/`search_code` branches did NOT relocate (D6),
    and the path-containment guard `_check_filepath` is IMPORTED from the kernel,
    never re-rolled.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from sr_agent.models.action import ActionClass
from sr_agent.orchestrator.action import _check_filepath

if TYPE_CHECKING:
    from sr_agent.models.action import Action


class AuditActionType(str, Enum):
    # ── READ-ONLY analyzers ──────────────────────────────────────────────
    build_graph = "build_graph"
    run_slither = "run_slither"
    run_mythril = "run_mythril"
    analyze_transactions = "analyze_transactions"
    decompile_bytecode = "decompile_bytecode"
    # ── WRITE / EXECUTE (kernel derives OOB-confirm from the class) ───────
    write_poc = "write_poc"
    run_tests = "run_tests"
    deploy_test_contract = "deploy_test_contract"


ACTION_CLASS_MAP: dict[AuditActionType, ActionClass] = {
    AuditActionType.build_graph: ActionClass.read_only,
    AuditActionType.run_slither: ActionClass.read_only,
    AuditActionType.run_mythril: ActionClass.read_only,
    AuditActionType.analyze_transactions: ActionClass.read_only,
    AuditActionType.decompile_bytecode: ActionClass.read_only,
    AuditActionType.write_poc: ActionClass.write_execute,
    AuditActionType.run_tests: ActionClass.write_execute,
    AuditActionType.deploy_test_contract: ActionClass.write_execute,
}

REVERSIBLE: dict[AuditActionType, bool] = {
    AuditActionType.build_graph: True,
    AuditActionType.run_slither: True,
    AuditActionType.run_mythril: True,
    AuditActionType.analyze_transactions: True,
    AuditActionType.decompile_bytecode: True,
    AuditActionType.write_poc: False,
    AuditActionType.run_tests: False,
    AuditActionType.deploy_test_contract: False,
}


def _validate_params(action: "Action", scope_root: Path) -> str | None:
    """Return a rejection reason string, or None if params are valid.

    Relocated behavior-preserving from the kernel `_validate_params` ladder
    (FR-005): only the branch operands changed to pack-local ids. The
    `read_file`/`search_code` branches stay kernel-side (D6) and are NOT here.
    """
    params = action.params

    if action.action_type == AuditActionType.run_slither:
        return _check_filepath(params.get("target"), scope_root, require_str=True)

    if action.action_type == AuditActionType.run_mythril:
        return _check_filepath(params.get("target"), scope_root, require_str=True)

    if action.action_type == AuditActionType.analyze_transactions:
        address = params.get("address")
        if not address:
            return "analyze_transactions requires 'address' param"
        blocks = params.get("max_blocks", 0)
        if int(blocks) > 10_000:
            return f"analyze_transactions max_blocks limit is 10000, got {blocks}"

    if action.action_type == AuditActionType.write_poc:
        return _check_filepath(params.get("finding_id"), None, require_str=True)

    if action.action_type == AuditActionType.deploy_test_contract:
        network = params.get("network", "")
        if network not in ("anvil", "localhost"):
            return f"deploy_test_contract only allowed on anvil/localhost, got {network!r}"

    return None

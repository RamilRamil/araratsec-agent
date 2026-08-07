"""Feature 043 - compiled attempt checkpoint (pure half).

Dual slots (non_vacuous / any_compile), restore-target selection, post-DET refuse
predicate, end-of-finding restore gate, and adopt-refusal event fields.
No I/O; no forge parsing; runner owns write_poc / artifact paths / logging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CheckpointSlot:
    source: str
    attempt: int
    compiled_real: bool
    outcome_summary: str = ""


@dataclass
class CheckpointState:
    non_vacuous: CheckpointSlot | None = None
    any_compile: CheckpointSlot | None = None


def is_compiled_real(*, compiled: bool, defects: list) -> bool:
    """FR-012 / research D1: same bar as runner compiled_real."""
    return bool(compiled) and not defects


def restore_target(state: CheckpointState) -> CheckpointSlot | None:
    if state.non_vacuous is not None:
        return state.non_vacuous
    if state.any_compile is not None:
        return state.any_compile
    return None


def restore_kind(state: CheckpointState) -> Literal["non_vacuous", "any_compile"] | None:
    if state.non_vacuous is not None:
        return "non_vacuous"
    if state.any_compile is not None:
        return "any_compile"
    return None


def refresh_slots(
    state: CheckpointState,
    *,
    source: str,
    attempt: int,
    compiled: bool,
    compiled_real: bool,
    outcome_summary: str = "",
) -> CheckpointState:
    """FR-007: any compile refreshes any_compile; non-vacuous also refreshes non_vacuous."""
    if not compiled:
        return state
    slot = CheckpointSlot(
        source=source,
        attempt=attempt,
        compiled_real=compiled_real,
        outcome_summary=outcome_summary,
    )
    new_non = state.non_vacuous
    if compiled_real:
        new_non = slot
    return CheckpointState(non_vacuous=new_non, any_compile=slot)


def should_refuse(*, compiled: bool, restore_target_present: bool) -> bool:
    return (not compiled) and restore_target_present


def should_emit_adopt_refusal(
    *,
    forge_compile_verdict_available: bool,
    compiled: bool,
    restore_target_present: bool,
) -> bool:
    """SC-007 / FR-011: never treat infra/sandbox miss as model-side adopt refusal."""
    if not forge_compile_verdict_available:
        return False
    return should_refuse(compiled=compiled, restore_target_present=restore_target_present)


def should_end_restore(*, compiled: bool, restore_target_present: bool) -> bool:
    """FR-008: restore only when active is still non-compiling and a target exists."""
    return (not compiled) and restore_target_present


def apply_refuse(working_body: str, state: CheckpointState) -> str:
    """Return restore-target source after a refuse; unchanged if no target."""
    slot = restore_target(state)
    if slot is None:
        return working_body
    return slot.source


def build_adopt_refusal_fields(
    state: CheckpointState,
    *,
    attempt: int,
    artifact_path: str,
) -> dict:
    """Fields for non-terminal compile_adopt_rejected (contracts/log-events.md)."""
    slot = restore_target(state)
    kind = restore_kind(state)
    if slot is None or kind is None:
        raise ValueError("build_adopt_refusal_fields requires a restore-target")
    return {
        "event": "compile_adopt_rejected",
        "attempt": attempt,
        "artifact_path": artifact_path,
        "restore_attempt": slot.attempt,
        "restore_kind": kind,
    }

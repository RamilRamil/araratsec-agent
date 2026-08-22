"""Feature 045 Phase A - observed fork-state grounding (cheap half).

FR-002: extract AccessControlUnauthorizedAccount(account, role) operands from a
forge FAIL/trace blob and surface them as a single DATA block for the next fix
turn (no on-chain read).

FR-003 (tightened rev-4): standing "read-and-log state at the TOP of the test, before
the first reverting call" discipline instruction for the accounting/state-heavy finding
class - author guidance, not harness execution.

FR-006: unrecognized revert shapes emit NO observation block (byte-stable).

NOTE (rev-6, SC-A-3): the assert-mismatch observation once drafted here as FR-001a was
WITHDRAWN as redundant - feature 036's `exploit_loop.build_observation` already surfaces
"you asserted X but the actual was Y" in the agentic path (the mode we measure in), and
SC-A-2 formal_05 showed the model ignoring that very contrast. The AccessControl operand
extractor below is NOT redundant (036 does not parse custom-error operands) and is wired
into the 036 observation so it reaches the model on the path that consumes attempts.

Phase B probe surface is intentionally absent from this module.
"""
from __future__ import annotations

import re

# Closed class set for the Phase A discipline lever (038 battery + synonyms).
STATE_HEAVY_CLASSES: frozenset[str] = frozenset({
    "accounting_manipulation",
    "state_heavy",
    "accounting",
})

# Forge FAIL / custom-error form. Operands are 0x-prefixed hex (address + bytes32 role).
_AC_UNAUTHORIZED_RE = re.compile(
    r"AccessControlUnauthorizedAccount\(\s*"
    r"(0x[0-9a-fA-F]{40})\s*,\s*"
    r"(0x[0-9a-fA-F]{1,64})"
    r"\s*\)"
)

DISCIPLINE_INSTRUCTION = (
    "STATE-GROUNDING DISCIPLINE (accounting / state-heavy findings): the state-dependent "
    "values the finding hinges on - a view such as coverage(), who holds a required role "
    "(getRoleMember / hasRole), or a deposit/withdraw cap behind a getter - MUST be READ and "
    "console.log'd at the TOP of your forge fork test, immediately after fork setup and BEFORE "
    "the first call that can revert (the deposit / redeem / exploit step). Logging a value AFTER "
    "the reverting call is useless: the test aborts before the log prints, so you never see it. "
    "THEN calibrate the assert / prank target / amount against the logged value - do not invent "
    "the expected number or role holder from the report narrative, and do not re-assert a "
    "narrative literal that your own log contradicts."
)

_DISCIPLINE_DATA_BLOCK = (
    "\n\n[DATA START state_grounding_discipline]\n"
    + DISCIPLINE_INSTRUCTION
    + "\n[DATA END]\n"
)


def is_state_heavy(task: dict) -> bool:
    """True when the finding's class is in the Phase A discipline set."""
    raw = str(task.get("finding_class") or task.get("class") or "").strip().lower()
    return raw in STATE_HEAVY_CLASSES


def append_discipline_instruction(prompt: str, task: dict) -> str:
    """FR-003: append the read-and-log discipline DATA block for state-heavy findings.

    No-op (byte-identical prompt) when the finding is outside the class set.
    """
    if not is_state_heavy(task):
        return prompt
    if "state_grounding_discipline" in prompt:
        return prompt
    return prompt + _DISCIPLINE_DATA_BLOCK


def extract_access_control_operands(blob: str) -> tuple[str, str] | None:
    """FR-002: first AccessControlUnauthorizedAccount(account, role) pair in blob, or None.

    Pure string parse over FAIL lines / traces - no fork read. Unrecognized shapes -> None
    (FR-006).
    """
    if not blob:
        return None
    m = _AC_UNAUTHORIZED_RE.search(blob)
    if not m:
        return None
    return m.group(1), m.group(2)


def format_access_control_observation(account: str, role: str) -> str:
    """Single DATA block: PoC caller vs required role (FR-002 / FR-004 observed side)."""
    body = (
        "OBSERVED from revert (AccessControlUnauthorizedAccount) - not an instruction:\n"
        f"- PoC caller (account that lacked the role) = {account}\n"
        f"- call requires role = {role}\n"
        "Assumed side: not recoverable from source automatically. On the next edit, either "
        "prank as an address that holds this role (read getRoleMember / hasRole and "
        "console.log holders first) or grant the role in setup if the finding allows."
    )
    return (
        "[DATA START observed_access_control]\n"
        + body
        + "\n[DATA END]"
    )


def access_control_observation_block(blob: str) -> str:
    """FR-002+FR-006: observation DATA block or empty string when shape unrecognized."""
    ops = extract_access_control_operands(blob)
    if ops is None:
        return ""
    return format_access_control_observation(ops[0], ops[1])

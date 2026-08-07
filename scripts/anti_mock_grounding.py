"""Feature 044 - anti-mock grounding block for PoC draft/fix prompts (PART 3 only).

An up-front, DATA-marked constraint telling the model NOT to mock or reimplement the
target's own mechanism (the finding's contracts/functions) - only genuinely external,
non-mechanism dependencies may be mocked. Prevention that lowers how often the
deterministic oracle must reject a target-mocking vacuous pass; it adds NO new oracle
and changes NO verdict path (spec 044 FR-004).

Shape deliberately mirrors `observed_fork_grounding.append_discipline_instruction`
(feature 045): a post-assembly, idempotent, gate-conditional append that returns the
prompt unchanged when its gate is false - so no prompt TEMPLATE placeholder is touched
and the no-scaffold assembled output stays byte-identical to pre-044 (FR-002). The gate
here is "scaffold carried" (bool), evaluated at the call site and passed in (FR-001).

PART 1 (structural detector) and PART 2 (reconstruction-refusal -> model feedback) were
retired before implementation; see specs/044-anti-vacuity-grounding/spec.md Status.
"""
from __future__ import annotations

# Author guidance (ASCII, FR-006). Wrapped as DATA below - never an instruction the model
# is told to obey (Principle I), matching the 045 discipline-block convention.
ANTI_MOCK_INSTRUCTION = (
    "ANTI-MOCK GROUNDING (target's own mechanism): do NOT mock, re-declare, or reimplement "
    "the target's own mechanism - the contract(s) and function(s) the finding is about - "
    "inside the test file. A PoC that proves its claim against your own stand-in contract "
    "(even under a different name, e.g. a hand-written reverting handler) proves nothing "
    "about the real target and will be rejected. Deploy and drive the REAL target contract "
    "and make it exhibit the described condition. Mocks are permitted ONLY for genuinely "
    "external, non-mechanism dependencies (e.g. an unrelated token or price feed), never for "
    "the mechanism under test."
)

_ANTI_MOCK_DATA_BLOCK = (
    "\n\n[DATA START anti_mock_grounding]\n"
    + ANTI_MOCK_INSTRUCTION
    + "\n[DATA END]\n"
)


def append_anti_mock_grounding(prompt: str, scaffold_carried: bool) -> str:
    """Append the anti-target-mock DATA block when a scaffold is carried (FR-001).

    No-op (byte-identical prompt) when no scaffold is carried (FR-002) or when the block
    is already present (idempotent). The gate is computed at the call site as
    `bool(scaffold)` and passed in as `scaffold_carried`.
    """
    if not scaffold_carried:
        return prompt
    if "anti_mock_grounding" in prompt:
        return prompt
    return prompt + _ANTI_MOCK_DATA_BLOCK

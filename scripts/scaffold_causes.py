"""Feature 040 - the shared, pure scaffold-failure cause taxonomy.

Single source of truth for:
- the two CLOSED cause sets (synthesis-attempt and finding-attempt levels, data-model.md),
- the cause -> nature map: exactly THREE natures (`harness-infra` / `synth-model` /
  `model`, FR-005). Success is NOT a fourth nature - it is carried by `is_ok` (causes
  `synthesized` / `proved`), so the nature-share denominator stays clean.
- classify_build_failure(blob) -> cause: a PURE function mapping a forge build-failure
  blob to one of `no_build:{path,toolchain,code}`. Called by the runner at the emission
  point (so the log holds ONE cause) AND re-usable by the offline classifier from the
  full stderr_signature - never an ad-hoc substring match duplicated at two sites.

Depends on nothing in poc_queue_runner (pure), so both the runner and scaffold_taxonomy
import it without a cycle. All values here are abstract cause names - no target material.
"""
from __future__ import annotations

# ── Closed cause sets (data-model.md) ────────────────────────────────────────
SYNTHESIS_CAUSES = frozenset({
    "synthesized",
    "no_output:model", "no_output:crash",
    "no_build:path", "no_build:toolchain", "no_build:code", "no_build:infra",
    "repair_exhausted:resolvable", "repair_exhausted:unresolvable",
})

FINDING_CAUSES = frozenset({
    "proved",
    "base-insufficient", "lookup_failed", "model",
    "not_triggered", "not_attempted:budget", "unclassified",
})

# ── cause -> nature (exactly 3 natures) ──────────────────────────────────────
# Authorship is what decides whether a failure may be excluded from a model's rate:
#   harness-infra  = environment/toolchain (model-independent)
#   synth-model    = the synthesis model (same model under test) authored a bad/absent base
#   model          = the exploit-body model
_NATURE: dict[str, str] = {
    # synthesis-attempt level
    "no_output:crash": "harness-infra",
    "no_build:path": "harness-infra",
    "no_build:toolchain": "harness-infra",
    "no_build:infra": "harness-infra",
    "repair_exhausted:resolvable": "harness-infra",  # a deterministic (our) fixer should have fired
    "no_output:model": "synth-model",
    "no_build:code": "synth-model",
    "repair_exhausted:unresolvable": "synth-model",
    # finding-attempt level
    "base-insufficient": "harness-infra",            # only when the lookup route could not run
    "lookup_failed": "model",                        # lookup ran; the model failed
    "model": "model",
}

# Success is carried separately, never as a nature.
_OK = frozenset({"synthesized", "proved"})

# Excluded from the nature-share denominator (makes a truncated run visible instead of
# silently shrinking the denominator).
_NOT_IN_DENOM = frozenset({"not_attempted:budget"})


def cause_nature(cause: str) -> str | None:
    """The author-nature of a terminal cause, or None.

    Returns one of {"harness-infra", "synth-model", "model"} for a failure cause; None
    for a success (`is_ok`), an excluded cause (`not_attempted:budget`), `unclassified`,
    or `not_triggered`. `not_triggered` deliberately has NO default nature - an
    unverified miss is not charged to the model column; the classifier promotes it to
    `model` ONLY via the fold rule when a concrete upstream model cause is found.
    """
    return _NATURE.get(cause)


def is_ok(cause: str) -> bool:
    """True for the success causes (`synthesized` / `proved`)."""
    return cause in _OK


def in_denominator(cause: str) -> bool:
    """Whether a finding-attempt cause counts toward the nature-share denominator.

    `not_attempted:budget` is excluded so a budget-cut run cannot silently publish a
    share over a shrunken denominator.
    """
    return cause not in _NOT_IN_DENOM


# ── Pure build-failure sub-classifier ────────────────────────────────────────
# Environment signatures (path/toolchain) are checked BEFORE the generic fallthrough to
# `no_build:code`, so an infra failure is never mislabelled as model-authored Solidity.
def classify_build_failure(blob: str) -> str:
    """Map a forge build-failure blob to one of `no_build:{path,toolchain,code}`.

    PURE, deterministic, target-free. Intended to run at the runner's emission point
    (one cause in the log) and be re-runnable by the offline classifier on the full,
    normalized `stderr_signature` - so emission-time classification is never irreversible.
    Does NOT emit `no_build:infra`: that is a SandboxUnavailable/timeout signal known from
    the exception type at the runner, not derivable from a compile blob.
    """
    b = blob.lower()
    # toolchain FIRST: forge's "Found Solidity sources, but no compiler versions are
    # available" contains the substring "source" and must not be misread as a path miss.
    if (("no compiler versions" in b and "available" in b) or "no solc version" in b):
        return "no_build:toolchain"
    # path/mount: the compiler could not find a source it was told to import.
    if ("not found" in b and ("searched:" in b or "source" in b)):
        return "no_build:path"
    # otherwise a genuine Solidity error in the (model-authored) base.
    return "no_build:code"

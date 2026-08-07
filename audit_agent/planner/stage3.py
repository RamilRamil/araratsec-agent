"""Stage 3 — deterministic finding synthesis / combination (T056, relay variant).

No LLM: two deterministic passes over the Stage 2 findings.

  1. Severity conjunction correction (reuses guardrails.severity.check_severity):
     mitigations cap severity at medium; many preconditions floor it at high.
  2. Combination: findings that interact (SIG-lite — same source file share state)
     are linked via combined_with. A conservative chain rule elevates a group of
     2+ unmitigated high/critical findings on the same target to a critical chain
     (blast-radius reasoning: interacting high-severity issues amplify).

Stage 3 returns transformed findings for the report; it does not write to memory
(append-only + supersedes requires human_input, so the raw Stage 2 records stay
as the audit trail and the report shows the synthesized view).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from audit_agent.guardrails.severity import check_severity
from audit_agent.finding import Finding, Severity

if TYPE_CHECKING:
    from audit_agent.planner.sig import StateInterferenceGraph

logger = logging.getLogger(__name__)

_RANK = {
    Severity.informational: 0, Severity.low: 1, Severity.medium: 2,
    Severity.high: 3, Severity.critical: 4,
}


@dataclass
class Stage3Result:
    findings: list[Finding]
    corrections: list[str] = field(default_factory=list)
    combinations: list[str] = field(default_factory=list)


def run_stage3(
    findings: list[Finding],
    sigs: dict[str, "StateInterferenceGraph"] | None = None,
) -> Stage3Result:
    """Correct severities and link/elevate interacting findings.

    If a per-file State Interference Graph is provided, findings combine only
    when their functions actually share state; otherwise the fallback links all
    findings in the same source file.
    """
    corrections: list[str] = []
    combinations: list[str] = []

    # Pass 1 — per-finding severity conjunction correction.
    for finding in findings:
        verdict = check_severity(finding)
        if verdict.was_corrected:
            finding.severity = verdict.final
            corrections.append(verdict.correction_reason or "")

    # Pass 2 — group by source file, then link by interference.
    groups: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        groups[finding.location.split(":")[0]].append(finding)

    for source_file, group in groups.items():
        if len(group) < 2:
            continue
        sig = (sigs or {}).get(source_file)

        def interacts(a: Finding, b: Finding) -> bool:
            if a is b:
                return False
            if sig is None:
                return True  # fallback: same file = interacting
            return sig.interferes(a.location.split(":")[-1], b.location.split(":")[-1])

        for finding in group:
            finding.combined_with = [g.finding_id for g in group if interacts(finding, g)]

        # Conservative chain rule: 2+ unmitigated high/critical findings that
        # interact with each other -> critical chain.
        severe = [
            f for f in group
            if _RANK[f.severity] >= _RANK[Severity.high] and not f.mitigations_present
        ]
        elevate = [f for f in severe if any(interacts(f, g) for g in severe)]
        if len(elevate) >= 2:
            for finding in elevate:
                finding.severity = Severity.critical
            combinations.append(
                f"{source_file}: {len(elevate)} interacting unmitigated high+ findings "
                f"→ critical chain ({', '.join(f.finding_id for f in elevate)})"
            )

    logger.info(
        "Stage 3: %d corrections, %d combination chains", len(corrections), len(combinations)
    )
    return Stage3Result(findings=findings, corrections=corrections, combinations=combinations)

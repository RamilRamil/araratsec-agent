"""Audit-domain escalation triggers (feature 004, R5).

The five finding-based triggers (#3–#7) split out of the kernel's
`evaluate_triggers`. The kernel keeps the domain-independent guards (irreversible
action, unauthorized memory status-change, resource limit) and calls this after
them; first match wins (order preserved). Injected via the pack; the kernel never
imports it.
"""
from __future__ import annotations

from sr_agent.guardrails.escalation import EscalationResult
from sr_agent.llm_core.schemas import EscalationTrigger
from audit_agent.finding import (
    Finding, FindingStatus, PoCStatus, Severity,
)


def _severity_rank(s: Severity) -> int:
    return {"informational": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}[s.value]


def domain_escalation(
    finding: "Finding | None" = None,
    existing_findings: "list[Finding] | None" = None,
) -> EscalationResult | None:
    """Triggers #3–#7. Returns the first that fires, or None."""
    if finding is None:
        return None

    # 3. Critical finding
    if finding.severity == Severity.critical:
        return EscalationResult(
            triggered=True, trigger=EscalationTrigger.critical_finding,
            detail=f"Critical severity finding at {finding.location}",
        )

    # 4. Unverified high severity
    if finding.severity == Severity.high and finding.status == FindingStatus.unverified:
        return EscalationResult(
            triggered=True, trigger=EscalationTrigger.unverified_high,
            detail=f"Unverified high-severity finding {finding.finding_id} at {finding.location}",
        )

    # 5. Mock test detected (PoC uses mock patterns)
    if finding.poc_status == PoCStatus.mock_review:
        return EscalationResult(
            triggered=True, trigger=EscalationTrigger.mock_test,
            detail=f"PoC for {finding.finding_id} uses mock patterns — human review required",
        )

    # 6. Contradicting findings — same location, conflicting severity/status
    for existing in existing_findings or []:
        if existing.location == finding.location and existing.function_name == finding.function_name:
            if abs(_severity_rank(existing.severity) - _severity_rank(finding.severity)) >= 2:
                return EscalationResult(
                    triggered=True, trigger=EscalationTrigger.contradicting_findings,
                    detail=(
                        f"Contradicting severity at {finding.location}: "
                        f"existing={existing.severity.value}, new={finding.severity.value}"
                    ),
                )

    # 7. Unknown pattern — bastet_tag is None on a non-informational finding
    if finding.bastet_tag is None and finding.severity not in (
        Severity.informational, Severity.low
    ):
        return EscalationResult(
            triggered=True, trigger=EscalationTrigger.unknown_pattern,
            detail=f"No Bastet tag on {finding.severity.value} finding {finding.finding_id}",
        )

    return None

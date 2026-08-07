"""Eval runner — recall / FPR / loop-completion over EVAL_CASES (T082).

Runs each `EvalCase` through the real `sr_agent.orchestrator.pipeline` audit
(Stage 1 SIG planning + local-model Stage 2 — relay is interactive and can't
run headlessly in a batch eval), then scores the resulting findings against
that case's ground truth. All metrics are deterministic Python, never
LLM-judged:

  recall@known_vulns := TP / (TP + FN), across every `EvalCriterion` in every
      case whose audit loop completed. A criterion is a TP if some reported
      finding matches its bastet_tag + function_name (substring) + location
      (substring) with severity >= min_severity.

  FPR := FP / (FP + TP). There are no true negatives in an open-ended
      vulnerability-finding task, so this is really a false-discovery
      proportion (share of reported findings not grounded in a known
      vulnerability) reported under the FPR name used by tasks.md/spec
      thresholds — documented here explicitly to avoid false rigor.

  loop_completion_rate := completed_cases / total_cases. A case fails to
  complete if the local model is unavailable or the pipeline raises/pauses
  instead of finishing — this measures pipeline reliability, not finding
  quality.

HARD dependency on `langfuse` (see eval/dataset.py) — `push_scores=True`
(default) requires a reachable Langfuse instance and
LANGFUSE_SECRET_KEY/LANGFUSE_PUBLIC_KEY configured; pass `push_scores=False`
to compute metrics locally only. Targets the installed langfuse>=3 OTel-based
client API (`create_trace_id()` + `start_as_current_observation()` +
`.create_score(trace_id=...)`), matching `sr_agent/eval/tracer.py`.
"""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from eval.dataset import EVAL_CASES, EvalCase, EvalCriterion
from sr_agent.llm_core.local_client import LocalClient
from sr_agent.memory.episodic import EpisodicMemory
from sr_agent.models.audit import AuditInput, Principal
from sr_agent.models.finding import Finding, Severity
from sr_agent.orchestrator.pipeline import start_audit

logger = logging.getLogger(__name__)

_RANK = {
    Severity.informational: 0, Severity.low: 1, Severity.medium: 2,
    Severity.high: 3, Severity.critical: 4,
}

EVAL_SECRET = b"eval-runner-secret-key-32-bytes!"


@dataclass
class CaseResult:
    case_id: str
    loop_completed: bool
    tp: int = 0
    fn: int = 0
    fp: int = 0
    matched_tags: list[str] = field(default_factory=list)
    missed_tags: list[str] = field(default_factory=list)
    skip_reason: str = ""


@dataclass
class EvalReport:
    results: list[CaseResult]
    recall: float
    fpr: float
    loop_completion_rate: float


def _reconstruct_findings(memory: EpisodicMemory, principal: Principal) -> list[Finding]:
    """Rebuild Finding objects from raw memory records.

    Mirrors `pipeline._finish`'s reconstruction (kept as an independent copy,
    not an import, so eval doesn't reach into pipeline internals). Notably
    this is PRE-Stage-3 severity correction — bastet_tag/function/location
    are unaffected by Stage 3, which only touches severity and combination,
    so this is accurate for criterion matching except a borderline
    min_severity case right at a Stage 3 correction boundary.
    """
    out: list[Finding] = []
    for record in memory.load_for_principal(principal):
        if not record.finding:
            continue
        payload = dict(record.finding)
        payload.pop("notes", None)
        payload.pop("notes_flags", None)
        try:
            out.append(Finding(**payload))
        except Exception:
            continue
    return out


def _criterion_matched(criterion: EvalCriterion, findings: list[Finding]) -> bool:
    min_rank = _RANK[Severity(criterion.min_severity)]
    for f in findings:
        if f.bastet_tag is None or f.bastet_tag.value != criterion.bastet_tag:
            continue
        if criterion.function_name and criterion.function_name.lower() not in f.function_name.lower():
            continue
        if criterion.location_contains and criterion.location_contains not in f.location:
            continue
        if _RANK[f.severity] < min_rank:
            continue
        return True
    return False


def _run_case(case: EvalCase, local_client: LocalClient) -> CaseResult:
    if not local_client.available():
        return CaseResult(
            case_id=case.case_id, loop_completed=False, fn=len(case.criteria),
            skip_reason=f"local model {local_client.model!r} unavailable",
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        memory = EpisodicMemory(tmp_path / "memory", EVAL_SECRET)
        principal = Principal(user_id="eval", platform="eval", project_id=case.case_id)
        audit_input = AuditInput(
            path=case.path, focus_files=[Path(f) for f in case.focus_files], principal=principal,
        )
        try:
            result = start_audit(
                audit_input, case.path, memory,
                relay_dir=tmp_path / "relay", runs_dir=tmp_path / "runs",
                output=str(tmp_path / "report.md"),
                stage2_provider="local", local_client=local_client,
            )
        except Exception as e:
            logger.warning("Eval case %s crashed: %s", case.case_id, e)
            return CaseResult(
                case_id=case.case_id, loop_completed=False,
                fn=len(case.criteria), skip_reason=f"{type(e).__name__}: {e}",
            )

        if result.status != "done":
            return CaseResult(
                case_id=case.case_id, loop_completed=False, fn=len(case.criteria),
                skip_reason=f"pipeline did not finish (status={result.status})",
            )

        findings = _reconstruct_findings(memory, principal)

    tp = fn = 0
    matched: list[str] = []
    missed: list[str] = []
    for criterion in case.criteria:
        if _criterion_matched(criterion, findings):
            tp += 1
            matched.append(criterion.bastet_tag)
        else:
            fn += 1
            missed.append(criterion.bastet_tag)

    known_tags = {c.bastet_tag for c in case.criteria}
    fp = sum(1 for f in findings if not f.bastet_tag or f.bastet_tag.value not in known_tags)

    return CaseResult(
        case_id=case.case_id, loop_completed=True, tp=tp, fn=fn, fp=fp,
        matched_tags=matched, missed_tags=missed,
    )


def run_eval(
    cases: list[EvalCase] | None = None,
    local_client: LocalClient | None = None,
    dataset_name: str = "sr-agent-eval",
    push_scores: bool = True,
) -> EvalReport:
    cases = EVAL_CASES if cases is None else cases
    client = local_client or LocalClient()

    results = [_run_case(case, client) for case in cases]
    for r in results:
        logger.info(
            "Eval %s: completed=%s tp=%d fn=%d fp=%d (%s)",
            r.case_id, r.loop_completed, r.tp, r.fn, r.fp, r.skip_reason,
        )

    total_tp = sum(r.tp for r in results)
    total_fn = sum(r.fn for r in results)
    total_fp = sum(r.fp for r in results)
    completed = sum(1 for r in results if r.loop_completed)

    report = EvalReport(
        results=results,
        recall=(total_tp / (total_tp + total_fn)) if (total_tp + total_fn) else 0.0,
        fpr=(total_fp / (total_fp + total_tp)) if (total_fp + total_tp) else 0.0,
        loop_completion_rate=(completed / len(results)) if results else 0.0,
    )

    if push_scores:
        _push_scores(report, dataset_name)

    return report


def _push_trace_scores(client, name: str, scores: dict[str, float]) -> None:
    """Open one throwaway root span to mint a trace_id, then attach `scores`
    to it. `create_score` addresses traces by id alone, but a trace with no
    observation on it is invisible in the Langfuse UI, hence the span."""
    trace_id = client.create_trace_id()
    with client.start_as_current_observation(
        trace_context={"trace_id": trace_id}, name=name, as_type="span",
    ):
        pass
    for score_name, value in scores.items():
        client.create_score(trace_id=trace_id, name=score_name, value=value)


def _push_scores(report: EvalReport, dataset_name: str) -> None:
    """Post per-case and aggregate scores to Langfuse. Hard dependency."""
    from langfuse import Langfuse

    client = Langfuse()
    for r in report.results:
        case_recall = (r.tp / (r.tp + r.fn)) if (r.tp + r.fn) else None
        scores = {"loop_completed": 1.0 if r.loop_completed else 0.0}
        if case_recall is not None:
            scores["recall"] = case_recall
        _push_trace_scores(client, f"{dataset_name}-{r.case_id}", scores)

    _push_trace_scores(client, f"{dataset_name}-summary", {
        "recall": report.recall,
        "fpr": report.fpr,
        "loop_completion_rate": report.loop_completion_rate,
    })
    client.flush()

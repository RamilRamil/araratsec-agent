"""Feature 040 - the offline, deterministic scaffold-failure taxonomy classifier (US2).

Reads attributed run logs (or target-free synthetic fixtures) and reports, per
model/class, the closed-set cause distribution at two levels (synthesis-attempt and
finding-attempt) plus the per-nature confound share at the finding-attempt level.

Design guarantees (contracts/taxonomy-cli.md):
- PURE: no model, no network; output is a function of input.
- HONEST NEGATIVE (FR-003): events lacking run_id/model are counted `unattributed` and
  NEVER given a per-model breakdown.
- DENOMINATOR HONESTY: per-nature share is over `attempted` finding-attempts, excludes
  `not_attempted:budget`, and is refused (null) when the run was budget-cut unless
  --allow-truncated is passed.
- FOLD RULE: a finding-attempt is attributed to its ROOT author - if its synthesis
  attempt failed, the finding's nature is the synthesis nature (so `synth-model` and
  `harness-infra` surface at the finding level and a downstream model-looking error is
  traced to the upstream base failure).

This is a REPORT. Per Constitution Principle IV it writes nowhere near the lesson store
or draft prompts - no observation here self-promotes into pipeline-steering knowledge.
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import Counter, defaultdict

import audit_agent.proof.scaffold_causes as sc

# Legacy (pre-instrumentation) scaffold events - used only to count `unattributed`.
_LEGACY_SCAFFOLD = {
    "scaffold_synthesis_failed", "scaffold_synthesized", "scaffold_insufficient",
    "scaffold_repair", "scaffold_repair_exhausted",
}
_NATURES = ("harness-infra", "synth-model", "model")


def _fold_nature(finding_cause: str, synth_causes: list[str]) -> str | None:
    """Attribute a finding-attempt to its root author.

    proved -> None (success). If any synthesis attempt for this finding FAILED, the base
    never arrived, so the finding's failure is charged to the synthesis nature (last
    attempt). Otherwise (synthesis succeeded or never ran) it is charged to the
    finding-level cause's own nature (which is None for an unverified `not_triggered`).
    """
    if sc.is_ok(finding_cause):
        return None
    failed = [c for c in synth_causes if not sc.is_ok(c)]
    if failed:
        return sc.cause_nature(failed[-1])
    return sc.cause_nature(finding_cause)


def classify(events: list[dict], *, allow_truncated: bool = False) -> dict:
    """Pure classifier - see module docstring. `events` is a list of parsed log dicts."""
    unattributed = 0
    synthesis_counts: Counter[str] = Counter()
    finding_counts: Counter[str] = Counter()
    by_model_synth: dict[str, Counter[str]] = defaultdict(Counter)
    by_model_find: dict[str, Counter[str]] = defaultdict(Counter)
    by_class_find: dict[str, Counter[str]] = defaultdict(Counter)
    synth_by_finding: dict[tuple[str, str], list[str]] = defaultdict(list)
    finding_terminal: dict[tuple[str, str], str] = {}

    for e in events:
        rid, model = e.get("run_id"), e.get("model")
        if not e.get("terminal"):
            if e.get("event") in _LEGACY_SCAFFOLD and (not rid or not model):
                unattributed += 1
            continue
        # a terminal event without full attribution cannot be placed
        if not rid or not model:
            unattributed += 1
            continue
        level, cause, fid = e.get("level"), e.get("cause"), e.get("finding_id")
        key = (rid, fid)
        if level == "synthesis_attempt":
            cause = cause if cause in sc.SYNTHESIS_CAUSES else "unclassified"
            synthesis_counts[cause] += 1
            by_model_synth[model][cause] += 1
            synth_by_finding[key].append(cause)
        elif level == "finding_attempt":
            cause = cause if cause in sc.FINDING_CAUSES else "unclassified"
            finding_counts[cause] += 1
            by_model_find[model][cause] += 1
            if e.get("finding_class"):
                by_class_find[e["finding_class"]][cause] += 1
            finding_terminal[key] = cause

    queued = len(finding_terminal)
    attempted = sum(1 for c in finding_terminal.values() if sc.in_denominator(c))
    truncated = attempted < queued

    nature_counts: Counter[str] = Counter()
    for key, fcause in finding_terminal.items():
        if not sc.in_denominator(fcause):
            continue
        nat = _fold_nature(fcause, synth_by_finding.get(key, []))
        if nat:
            nature_counts[nat] += 1

    if truncated and not allow_truncated:
        nature_share: dict[str, float] | None = None
    else:
        denom = attempted or 1
        nature_share = {n: nature_counts.get(n, 0) / denom for n in _NATURES}

    by_model = {
        m: {"synthesis": dict(by_model_synth.get(m, {})), "finding": dict(by_model_find.get(m, {}))}
        for m in set(by_model_synth) | set(by_model_find)
    }

    return {
        "queued": queued,
        "attempted": attempted,
        "terminal_emitted": queued,
        "truncated": truncated,
        "synthesis_counts": dict(synthesis_counts),
        "finding_counts": dict(finding_counts),
        "by_model": by_model,
        "by_class": {k: dict(v) for k, v in by_class_find.items()},
        "nature_share": nature_share,
        "unattributed": unattributed,
        "caveat": ("Diagnostic harness-reliability measurement on a bounded diagnostic run; "
                   "NOT a model-capability estimate."),
    }


def _read_events(patterns: list[str]) -> tuple[list[dict], int]:
    """Read JSONL from files/globs. Malformed lines are counted, not fatal."""
    events: list[dict] = []
    malformed = 0
    paths: list[str] = []
    for p in patterns:
        paths.extend(sorted(glob.glob(p)) or [p])
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    malformed += 1
    return events, malformed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline scaffold-failure taxonomy classifier (040 US2).")
    ap.add_argument("--log", nargs="+", required=True, help="run-log JSONL file(s) or glob(s)")
    ap.add_argument("--out", help="write the taxonomy JSON here (else stdout)")
    ap.add_argument("--allow-truncated", action="store_true",
                    help="publish nature_share even when the run was budget-cut (attempted < queued)")
    args = ap.parse_args(argv)

    events, malformed = _read_events(args.log)
    out = classify(events, allow_truncated=args.allow_truncated)
    out["source"] = list(args.log)
    if malformed:
        out["malformed_lines"] = malformed
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

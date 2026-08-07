"""Ground-truth benchmark for vulnerability DISCOVERY (spec 023) — an operator rig.

Answers "what do we miss?" with a number, per vulnerability class. Loads curated
cases from an EXTERNAL dataset root (`SR_BENCH_ROOT`), runs a pluggable detector,
matches its findings against human-curated ground truth, and scores recall (overall
and PER BastetTag), precision, and a NAMED missed list.

Design rules this file exists to uphold:
  - The dataset (targets, reports, findings, paths) NEVER enters the agent repo —
    the root and every case path are validated EXTERNAL, results are written back
    under that root. (memory: feedback_no_target_code_in_agent)
  - Matching is CONSERVATIVE: credit only on (same normalized location) AND (same
    tag). A permissive matcher would inflate recall exactly the way "it compiled"
    once inflated PoC quality (`_poc_defects` / project_poc_vacuous_pass). A
    measuring stick must under-report, never over-report.
  - Ground truth is human-curated (transcribed from a published audit). If a model
    authored it, we would be measuring a model against a model.
  - No prefiltering: every ground-truth finding is scored.
  - Scoring itself is pure — no model, no network. (Detectors may use one.)

It lives in `scripts/` (not `sr_agent/eval/`) because it imports the audit pack's
taxonomy, and a kernel→pack import would violate the kernel/pack boundary.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from audit_agent.finding import BastetTag

_AGENT_ROOT = Path(__file__).resolve().parents[1]


class BenchError(Exception):
    """Bad dataset root/case/manifest/tag — always loud, never a silent skip."""


# ── entities ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GroundTruth:
    finding_id: str
    bastet_tag: BastetTag
    location: str
    function_name: str
    severity: str = "medium"


@dataclass(frozen=True)
class Candidate:
    finding_id: str
    bastet_tag: BastetTag | None      # None can NEVER be credited
    location: str
    function_name: str
    severity: str = "informational"


@dataclass
class Case:
    case_id: str
    truth: list[GroundTruth]
    target_path: Path | None = None
    repo_url: str = ""
    commit: str = ""
    report_path: Path | None = None


@dataclass
class MatchResult:
    matched: list[tuple[Candidate, GroundTruth]] = field(default_factory=list)
    missed: list[GroundTruth] = field(default_factory=list)
    spurious: list[Candidate] = field(default_factory=list)
    needs_review: list[tuple[Candidate, GroundTruth, str]] = field(default_factory=list)


@dataclass
class Scorecard:
    case_id: str
    detector: str
    truth_n: int
    produced_n: int
    matched_n: int
    recall: float
    precision: float
    per_tag_recall: dict[str, float | None]
    missed_named: list[dict]
    needs_review_n: int
    spurious_n: int

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id, "detector": self.detector,
            "truth_n": self.truth_n, "produced_n": self.produced_n,
            "matched_n": self.matched_n, "recall": self.recall,
            "precision": self.precision, "per_tag_recall": self.per_tag_recall,
            "missed_named": self.missed_named,
            "needs_review_n": self.needs_review_n, "spurious_n": self.spurious_n,
        }


# ── loading (external-only, loud validation) ─────────────────────────────────


def _external(p: Path, what: str) -> Path:
    """Resolve and refuse anything inside the agent repo (target material stays out)."""
    r = Path(p).expanduser().resolve()
    if r == _AGENT_ROOT or _AGENT_ROOT in r.parents:
        raise BenchError(f"{what} must be EXTERNAL to the agent repo, got: {r}")
    return r


def _tag(raw: str, ctx: str) -> BastetTag:
    try:
        return BastetTag(raw)
    except ValueError:
        raise BenchError(
            f"{ctx}: unknown bastet_tag {raw!r} — not in the taxonomy. Fix the label; "
            "a silent skip would quietly shrink the recall denominator."
        ) from None


def load_case(case_dir: Path) -> Case:
    case_dir = _external(case_dir, "case dir")
    manifest_p, labels_p = case_dir / "case.json", case_dir / "labels.json"
    for p in (manifest_p, labels_p):
        if not p.is_file():
            raise BenchError(f"missing {p.name} in {case_dir}")
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    case_id = str(manifest.get("case_id") or case_dir.name)

    has_path, has_url = bool(manifest.get("target_path")), bool(manifest.get("repo_url"))
    if has_path == has_url:
        raise BenchError(f"{case_id}: provide exactly one of target_path / repo_url")

    truth: list[GroundTruth] = []
    for rec in json.loads(labels_p.read_text(encoding="utf-8")):
        truth.append(GroundTruth(
            finding_id=str(rec["finding_id"]),
            bastet_tag=_tag(str(rec["bastet_tag"]), f"{case_id}/{rec.get('finding_id')}"),
            location=str(rec["location"]),
            function_name=str(rec.get("function_name", "")),
            severity=str(rec.get("severity", "medium")),
        ))
    return Case(
        case_id=case_id, truth=truth,
        target_path=_external(Path(manifest["target_path"]), "target_path") if has_path else None,
        repo_url=str(manifest.get("repo_url", "")),
        commit=str(manifest.get("commit", "")),
        report_path=(Path(manifest["report_path"]).expanduser()
                     if manifest.get("report_path") else None),
    )


def load_dataset(root: Path) -> list[Case]:
    root = _external(root, "bench root")
    cases_dir = root / "cases"
    if not cases_dir.is_dir():
        raise BenchError(f"no cases/ under {root}")
    return [load_case(d) for d in sorted(cases_dir.iterdir()) if d.is_dir()]


# ── matching (INTEGRITY-CRITICAL — must never inflate) ───────────────────────


def normalize_location(location: str, function_name: str) -> tuple[str, str]:
    """(file-basename-or-contract, function) lowercased — path-insensitive."""
    base = Path(str(location).strip()).name.strip().lower()
    return (base, str(function_name).strip().lower())


def match_findings(produced: list[Candidate], truth: list[GroundTruth]) -> MatchResult:
    """Credit ONLY on same normalized location AND same tag. Everything else is
    classified but never counted as found — see the module docstring."""
    res = MatchResult()
    unclaimed = list(truth)
    for cand in sorted(produced, key=lambda c: c.finding_id):
        hit: GroundTruth | None = None
        near: tuple[GroundTruth, str] | None = None
        for gt in unclaimed:
            same_loc = normalize_location(cand.location, cand.function_name) == \
                normalize_location(gt.location, gt.function_name)
            same_tag = cand.bastet_tag is not None and cand.bastet_tag == gt.bastet_tag
            if same_loc and same_tag:
                hit = gt
                break
            if same_loc and near is None:
                near = (gt, "tag_mismatch")
            elif same_tag and near is None:
                near = (gt, "location_mismatch")
        if hit is not None:
            res.matched.append((cand, hit))
            unclaimed.remove(hit)
        elif near is not None:
            res.needs_review.append((cand, near[0], near[1]))
        else:
            res.spurious.append(cand)
    res.missed = sorted(unclaimed, key=lambda g: g.finding_id)
    return res


# ── scoring ──────────────────────────────────────────────────────────────────


def score(case: Case, detector: str, m: MatchResult, produced_n: int) -> Scorecard:
    truth_n, matched_n = len(case.truth), len(m.matched)
    per_tag: dict[str, float | None] = {}
    for tag in sorted({g.bastet_tag for g in case.truth}, key=lambda t: t.value):
        denom = [g for g in case.truth if g.bastet_tag == tag]
        num = [1 for _c, g in m.matched if g.bastet_tag == tag]
        per_tag[tag.value] = round(len(num) / len(denom), 4) if denom else None
    return Scorecard(
        case_id=case.case_id, detector=detector, truth_n=truth_n, produced_n=produced_n,
        matched_n=matched_n,
        recall=round(matched_n / truth_n, 4) if truth_n else 0.0,
        precision=round(matched_n / produced_n, 4) if produced_n else 0.0,
        per_tag_recall=per_tag,
        missed_named=[
            {"finding_id": g.finding_id, "bastet_tag": g.bastet_tag.value,
             "location": g.location, "function_name": g.function_name, "severity": g.severity}
            for g in m.missed
        ],
        needs_review_n=len(m.needs_review), spurious_n=len(m.spurious),
    )


def render(s: Scorecard) -> str:
    lines = [
        f"case={s.case_id} detector={s.detector}",
        f"  recall    {s.recall:.2%}  ({s.matched_n}/{s.truth_n})",
        f"  precision {s.precision:.2%}  ({s.matched_n}/{s.produced_n})"
        f"   needs_review={s.needs_review_n} spurious={s.spurious_n}",
        "  recall per class:",
    ]
    for tag, v in s.per_tag_recall.items():
        lines.append(f"    {tag:<34} {'n/a' if v is None else f'{v:.2%}'}")
    lines.append(f"  MISSED ({len(s.missed_named)}):")
    for g in s.missed_named:
        lines.append(f"    {g['finding_id']:<8} {g['bastet_tag']:<28} "
                     f"{g['location']}:{g['function_name']}")
    return "\n".join(lines)


def write_result(root: Path, s: Scorecard) -> Path:
    out = _external(root, "bench root") / "results"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{s.case_id}.{s.detector}.json"
    p.write_text(json.dumps(s.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return p


# ── detectors ────────────────────────────────────────────────────────────────
# Honest flag→tag map. Only flags with a DEFENSIBLE tag are emitted. Flags with no
# honest tag (inline_assembly, native_transfer, native_send, low_level_call,
# low_level_call_value, selfdestruct, weak_randomness — the taxonomy has no
# randomness tag) emit NOTHING: inventing a tag to score points is the exact
# self-deception this rig exists to prevent. Omitting a real signal would be the
# same lie in the other direction — hence external_call_before_state_write (a real
# reentrancy SHAPE: external call then a state write) IS mapped.
_FLAG_TAG: dict[str, BastetTag] = {
    "tx_origin_auth": BastetTag.incorrect_access_control,
    "delegatecall": BastetTag.delegatecall_injection,
    "timestamp_dependence": BastetTag.timestamp_dependence,
    "external_call_before_state_write": BastetTag.reentrancy,
}


def _case_files(case: Case) -> list[Path]:
    if case.target_path is None:
        raise BenchError(
            f"{case.case_id}: uses repo_url — clone it and set target_path (v1 needs local files)"
        )
    return sorted(p for p in case.target_path.rglob("*.sol") if p.is_file())


def heuristic_detector(case: Case) -> list[Candidate]:
    """Today's Stage-1 red-flag scan, mapped to tags where honest. The floor.

    Uses the pack's extract_functions/score_function directly: run_stage1 returns
    only prioritized "file:function" strings and DISCARDS the flags we need.
    """
    from audit_agent.planner.stage1 import extract_functions, score_function

    out: list[Candidate] = []
    n = 0
    for path in _case_files(case):
        src = path.read_text(encoding="utf-8", errors="replace")
        for name, body, _line in extract_functions(src):
            _s, flags = score_function(body)
            for flag in flags:
                tag = _FLAG_TAG.get(flag)
                if tag is None:
                    continue          # no honest tag → emit nothing
                n += 1
                out.append(Candidate(
                    finding_id=f"H-{n:03d}", bastet_tag=tag,
                    location=path.name, function_name=name,
                ))
    return out


def make_llm_detector(provider: str, model: str, host: str) -> "object":
    """One unaided model pass per file — the 'what does a model find alone' number.

    Reuses the pack's analyze_target (already DATA-wraps the code and returns the
    label shape, enum-enforced) with a spec-022 provider client. Imported lazily so
    the offline scoring path pulls no heavy deps.
    """
    def _detect(case: Case) -> list[Candidate]:
        from scripts.poc_queue_runner import GEN_TIMEOUT_S, build_generation_client
        from audit_agent.analyze import analyze_target

        client = build_generation_client(provider, model, host, GEN_TIMEOUT_S)
        out: list[Candidate] = []
        for path in _case_files(case):          # every file — no prefiltering (FR-009)
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
                res = analyze_target(client, path.name, src)
            except Exception as e:              # one bad target must not kill the run
                print(f"  ! {path.name}: {e}", file=sys.stderr)
                continue
            for f in res.findings:
                out.append(Candidate(
                    finding_id=f.finding_id, bastet_tag=f.bastet_tag,
                    location=f.location, function_name=f.function_name,
                    severity=str(getattr(f.severity, "value", f.severity)),
                ))
        return out
    return _detect


DETECTORS: dict[str, object] = {"heuristic": heuristic_detector}


def resolve_detector(name: str, args: argparse.Namespace) -> object:
    if name == "llm":
        return make_llm_detector(args.provider, args.model, args.host)
    if name in DETECTORS:
        return DETECTORS[name]
    raise BenchError(f"unknown detector {name!r} (have: {sorted(DETECTORS)} + 'llm')")


# ── CLI ──────────────────────────────────────────────────────────────────────


def _root(args: argparse.Namespace) -> Path:
    raw = args.root or os.environ.get("SR_BENCH_ROOT", "")
    if not raw:
        raise BenchError("set SR_BENCH_ROOT (or --root) to the EXTERNAL dataset root")
    return Path(raw)


def _cmd_cases(args: argparse.Namespace) -> int:
    for c in load_dataset(_root(args)):
        print(f"{c.case_id:<20} truth={len(c.truth):<4} target={c.target_path or c.repo_url}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    root = _root(args)
    cases = [c for c in load_dataset(root) if not args.case or c.case_id == args.case]
    if not cases:
        raise BenchError(f"no case matched {args.case!r}")
    detector = resolve_detector(args.detector, args)
    for case in cases:
        produced = detector(case)
        card = score(case, args.detector, match_findings(produced, case.truth), len(produced))
        print(render(card))
        print(f"  -> {write_result(root, card)}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bench", description="Discovery benchmark (spec 023)")
    p.add_argument("--root", default="",
                   help="dataset root (default: $SR_BENCH_ROOT); must be EXTERNAL")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="score a detector over the dataset")
    r.add_argument("--detector", default="heuristic", help="heuristic | llm | <registered>")
    r.add_argument("--case", default="", help="only this case id")
    r.add_argument("--provider", choices=["local", "openrouter", "gemini"], default="local",
                   help="llm detector only (spec 022 providers)")
    r.add_argument("--model", default="", help="llm detector only; empty = provider default")
    r.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    r.set_defaults(func=_cmd_run)

    c = sub.add_parser("cases", help="list loaded cases")
    c.set_defaults(func=_cmd_cases)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BenchError as e:
        print(f"bench: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

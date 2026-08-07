"""Proof-pipeline eval (feature 026) - a measuring instrument for the PoC-workability harness.

SIBLING to the discovery benchmark (`bench.py`, spec 023), NOT an extension of it. Two orthogonal
axes: `bench.py` scores DISCOVERY (given a target, did we find the bug); this scores PROOF (given a
target AND a known finding AND its fix, can the harness produce a VERIFIED proof). It reuses bench.py's
disciplines - external dataset root, nothing committed, offline scoring - but is a different instrument.

It runs the existing harness (`poc_queue_runner.py`) as a BLACK BOX via its `--only`/`--fix-patch`
interface, N times per case, and reports two things:

  1. PRIMARY - the pooled fraction of case-runs reaching `passed_verified` (spec 025: falsification
     ran and the proof broke on the fix - the only trustworthy success), as a 95% Jeffreys Beta
     credible INTERVAL, never a single point. It widens with smaller N, so an underpowered run reads
     as "wide, not decisive" rather than a confident number.

  2. DIAGNOSTIC - a per-stage attrition FUNNEL (extract → draft → compiled → real_pass → verified)
     with the NAMED cases that died at each stage. It says WHAT to fix next (real_pass high but
     verified zero → the fixes are the problem, not the exploits - this session's exact situation).

Honesty rules, load-bearing:
  - The verified count is EXACTLY the harness's own `passed_verified` outcomes - never inferred, never
    model-judged. NO model anywhere in the scoring path (the same reason model-as-judge was rejected
    for the discovery benchmark). Guarded by tests/architecture/test_proof_bench_no_model.py.
  - A comparison across configs differing in anything but the harness version is FLAGGED - the exact
    guard the "3/5 vs 2/5" misread lacked.
  - Every report states N, the interval width, and that the case set is a tuned-on DEV set measuring
    within-set regression/progress, NOT absolute capability.

No scipy/numpy - the Beta quantile is a stdlib `betai` continued fraction + bisection (Decision 3).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]

# The attrition ladder, in order. A case-run's `stage` is the FURTHEST it reached.
STAGES = ("extracted", "draft", "compiled", "real_pass", "verified")
# Off-ladder buckets: never got extracted, or the run itself failed (infra, not proving).
NOT_EXTRACTED = "not_extracted"
ERROR = "error"

# Grace over the harness's own `--max-minutes` budget before the eval hard-kills the child: the
# harness should always get to stop itself and report first, so this trips only on a real wedge
# (a stuck forge/Docker child the harness's in-loop budget cannot interrupt).
_HARNESS_TIMEOUT_MARGIN_S = 300.0


class ProofBenchError(Exception):
    """Bad dataset root / case manifest / missing fix - always loud, never a silent skip."""


# ── entities ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Case:
    """One proof-eval case: a confirmed, FIX-BEARING finding. Leads are not cases (feature 026
    FR-009) - a lead is promoted to a confirmed finding (then its operator fix is authored and it
    enters the set like any other case) or discarded. Lives outside the agent repo."""
    case_id: str
    target_path: Path
    report_path: Path
    finding_id: str
    fix_path: Path
    # feature 028: the curated finding - human ground truth transcribed from the report (like the
    # discovery benchmark's labels and the operator fix), so the eval PINS a fixed finding instead
    # of re-running nondeterministic model extraction every run. Required (loud on absent/empty).
    title: str
    location: str
    description: str
    # feature 037 G1: OPTIONAL finding CLASS. Empty when the battery is unlabelled (back-compatible:
    # existing case.json without a class still loads). When present it enables the class-stratified
    # report (G2) - survival is class-dependent (035 FR-018), so a scalar pass-rate hides the map.
    finding_class: str = ""


@dataclass(frozen=True)
class RunConfig:
    """The pinned experimental conditions of a result set. Recorded so a comparison across configs
    differing in anything but `harness_version` can be flagged (US4) - the discipline the
    "3/5 vs 2/5" misread lacked."""
    case_set_id: str
    provider: str
    model: str
    scaffold: str
    example: str
    settings: dict
    n: int
    harness_version: str

    def to_dict(self) -> dict:
        return {"case_set_id": self.case_set_id, "provider": self.provider, "model": self.model,
                "scaffold": self.scaffold, "example": self.example, "settings": self.settings,
                "n": self.n, "harness_version": self.harness_version}


@dataclass(frozen=True)
class CaseOutcome:
    """The harness's verdict for ONE case-run. `stage` is the furthest stage reached;
    `stage == "verified"` IFF `outcome == "passed_verified"`, so the funnel's top and the interval's
    numerator cannot drift apart (feature 026 A4)."""
    case_id: str
    run_idx: int
    stage: str
    outcome: str          # the harness's task_done outcome, or "" for an off-ladder death
    verify_reason: str = ""

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "run_idx": self.run_idx, "stage": self.stage,
                "outcome": self.outcome, "verify_reason": self.verify_reason}


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float
    mass: float
    successes: int
    trials: int

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def to_dict(self) -> dict:
        return {"lo": round(self.lo, 4), "hi": round(self.hi, 4), "width": round(self.width, 4),
                "mass": self.mass, "successes": self.successes, "trials": self.trials}


@dataclass(frozen=True)
class Funnel:
    survivors: dict          # stage -> count of case-runs that reached AT LEAST that stage
    casualties: dict         # stage -> [case_id, ...] whose furthest stage was exactly below this one
    off_ladder: dict         # NOT_EXTRACTED / ERROR -> [case_id, ...]

    def to_dict(self) -> dict:
        return {"survivors": self.survivors, "casualties": self.casualties,
                "off_ladder": self.off_ladder}


@dataclass(frozen=True)
class Report:
    interval: Interval
    funnel: Funnel
    config: RunConfig
    # feature 037 G2: per-class credible interval, keyed by finding_class. Empty when the battery is
    # unlabelled. NEVER replaces the headline interval - it stratifies it (035 FR-018), so a
    # class-dependent wall is readable instead of hidden inside one scalar.
    by_class: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"interval": self.interval.to_dict(), "funnel": self.funnel.to_dict(),
             "config": self.config.to_dict()}
        if self.by_class:
            d["by_class"] = {k: iv.to_dict() for k, iv in self.by_class.items()}
        return d


# ── external-only loading (mirrors bench.py exactly) ──────────────────────────

def _external(p: Path, what: str) -> Path:
    """Resolve and refuse anything inside the agent repo (target/fix material stays out)."""
    r = Path(p).expanduser().resolve()
    if r == _AGENT_ROOT or _AGENT_ROOT in r.parents:
        raise ProofBenchError(f"{what} must be EXTERNAL to the agent repo, got: {r}")
    return r


def load_case(case_dir: Path) -> Case:
    """Load one case manifest. A case with no `fix_path` (or whose fix file is absent) is a LOUD
    error, UNCONDITIONALLY - every case is a confirmed fix-bearing finding (FR-008). `passed_verified`
    is unreachable without a fix, so a fix-less manifest is an error, not a silent skip."""
    case_dir = _external(case_dir, "case dir")
    manifest_p = case_dir / "case.json"
    if not manifest_p.is_file():
        raise ProofBenchError(f"missing case.json in {case_dir}")
    m = json.loads(manifest_p.read_text(encoding="utf-8"))
    case_id = str(m.get("case_id") or case_dir.name)

    fix_raw = m.get("fix_path")
    if not fix_raw:
        raise ProofBenchError(
            f"{case_id}: no fix_path - every proof-eval case needs an operator fix "
            f"(verified is unreachable without one; a lead is promoted or discarded, not a case)")
    fix_path = _external(Path(fix_raw), f"{case_id} fix_path")
    if not fix_path.is_file():
        raise ProofBenchError(f"{case_id}: fix_path does not exist: {fix_path}")

    # feature 028: the curated finding is REQUIRED (empty == missing) - a case must pin its own
    # ground-truth finding, never silently fall back to nondeterministic model extraction.
    for key in ("target_path", "report_path", "finding_id", "title", "location", "description"):
        if not str(m.get(key, "")).strip():
            raise ProofBenchError(
                f"{case_id}: missing {key} - a proof-eval case must carry its curated finding "
                f"(title/location/description) so it can be pinned; no fallback to model extraction")
    return Case(
        case_id=case_id,
        target_path=_external(Path(m["target_path"]), f"{case_id} target_path"),
        report_path=Path(m["report_path"]).expanduser(),
        finding_id=str(m["finding_id"]),
        fix_path=fix_path,
        title=str(m["title"]),
        location=str(m["location"]),
        description=str(m["description"]),
        # feature 037 G1: OPTIONAL - accepts either `class` or `finding_class`, empty if absent.
        finding_class=str(m.get("finding_class") or m.get("class") or ""),
    )


def load_dataset(root: Path) -> list[Case]:
    root = _external(root, "proof-bench root")
    cases_dir = root / "cases"
    if not cases_dir.is_dir():
        raise ProofBenchError(f"no cases/ under {root}")
    return [load_case(d) for d in sorted(cases_dir.iterdir()) if d.is_dir()]


# ── the Beta credible interval - stdlib only (Decision 3) ─────────────────────

_BETACF_ITMAX = 300
_BETACF_EPS = 3e-14
_PPF_TOL = 1e-12
_PPF_ITMAX = 200


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Numerical Recipes, Lentz). Deterministic:
    fixed iteration cap + tolerance, no library."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for mm in range(1, _BETACF_ITMAX + 1):
        m2 = 2 * mm
        aa = mm * (b - mm) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + mm) * (qab + mm) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < _BETACF_EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b) = the Beta(a,b) CDF at x. stdlib `math` only."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1.0 - x))
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(p: float, a: float, b: float) -> float:
    """Inverse Beta CDF (quantile) by bisection on `_betai`. Deterministic (fixed tol/itmax)."""
    lo, hi = 0.0, 1.0
    for _ in range(_PPF_ITMAX):
        mid = 0.5 * (lo + hi)
        if _betai(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < _PPF_TOL:
            break
    return 0.5 * (lo + hi)


def credible_interval(successes: int, trials: int, mass: float = 0.95) -> Interval:
    """95% equal-tailed JEFFREYS credible interval for the verified rate: posterior
    `Beta(s+0.5, trials-s+0.5)`. Jeffreys (the 0.5/0.5 prior) is chosen because it stays BOUNDED and
    sensible at s=0 and s=trials - the small-N regime this instrument lives in - where a uniform/Wald
    interval collapses (research Decision 2/3)."""
    if trials < 0 or successes < 0 or successes > trials:
        raise ProofBenchError(f"bad (successes, trials) = ({successes}, {trials})")
    a = successes + 0.5
    b = (trials - successes) + 0.5
    tail = (1.0 - mass) / 2.0
    lo = 0.0 if trials == 0 else _beta_ppf(tail, a, b)
    hi = 1.0 if trials == 0 else _beta_ppf(1.0 - tail, a, b)
    return Interval(lo=lo, hi=hi, mass=mass, successes=successes, trials=trials)


# ── feature 038: interval dominance + pairwise resolution (STRICTLY ADDITIVE) ──
# New module-level functions only - `credible_interval`/`build_by_class`/`score`/`Report` are
# untouched, so a 037 G2 fixture replays byte-identical (contract B9 / SC-005). The credible LEVEL
# is the interval's existing `mass` field: an interval built at 0.95 vs 0.50 is a different bar
# (B4), which is exactly why the level is pre-registered before the run (FR-017).

def dominates(a: Interval, b: Interval) -> bool:
    """feature 038 (FR-017): interval A dominates B iff A's credible interval lies ENTIRELY above
    B's - `a.lo > b.hi`. Overlapping intervals never yield a dominance claim (SC-010). The bar is
    whatever credible level (`mass`) the intervals were built at - a narrower 0.50 interval can
    separate a pair that a 0.95 interval leaves overlapping (B4)."""
    return a.lo > b.hi


def resolve(a: Interval, b: Interval) -> str:
    """Pairwise resolution at the intervals' credible level: `resolved` iff one dominates the other,
    else `unresolved@N` (they overlap). Resolution is a PAIR property, never a class property
    (SC-008) - a class is 'resolved' only via its separated pairs, never by fiat."""
    return "resolved" if dominates(a, b) or dominates(b, a) else "unresolved@N"


# ── comparison: overlap test (US1) + config-mismatch guard (US4) ──────────────

def compare(a: Report, b: Report) -> dict:
    """Compare two result sets. FIRST (US4) refuse if their configs differ in anything but the
    harness version - a delta across incomparable configs is meaningless (the "3/5 vs 2/5" trap).
    Then (US1) the interval overlap test: disjoint → a decided direction; overlapping → "not yet
    distinguishable", never a false winner."""
    diffs = _config_diffs(a.config, b.config)
    if diffs:
        return {"comparable": False, "reason": "config_mismatch", "differing_fields": diffs,
                "note": "pin everything but the harness version; this delta is not trustworthy"}
    ia, ib = a.interval, b.interval
    if ia.hi < ib.lo:
        verdict = "b_better"
    elif ib.hi < ia.lo:
        verdict = "a_better"
    else:
        verdict = "not_distinguishable"
    return {"comparable": True, "verdict": verdict,
            "a": ia.to_dict(), "b": ib.to_dict()}


def _config_diffs(a: RunConfig, b: RunConfig) -> list[str]:
    """Every field that differs EXCEPT harness_version (the intended independent variable)."""
    da, db = a.to_dict(), b.to_dict()
    return sorted(k for k in da if k != "harness_version" and da[k] != db[k])


# ── event stream → stage (US2); the fragile coupling to the runner's events ───

def _stage_of(events: list[dict], finding_id: str) -> str:
    """The FURTHEST stage one case-run reached, from the harness's own event stream.

    Coupling to the runner's real event shapes (verified against poc_queue_runner.py):
      - `extracted` carries `ids` = ALL findings' ids; a case counts as extracted ONLY when its
        `finding_id` is among them (a bare event does not qualify - extraction emits everyone).
        `only_ids_not_found` (or the id simply absent) → NOT_EXTRACTED.
      - `written` → draft; `tested` carries `compiled`/`real_pass` booleans per attempt;
        `task_done.outcome == passed_verified` → verified.
      - `run_error`/`sandbox_unavailable`/`timeout` → ERROR (infra, neither success nor a
        proving-failure)."""
    fid = str(finding_id).lower()
    by = lambda name: [e for e in events if e.get("event") == name]

    if by("run_error") or by("sandbox_unavailable") or by("timeout"):
        return ERROR
    extracted = by("extracted")
    got = any(fid in {str(i).lower() for i in e.get("ids", [])} for e in extracted)
    if not got or by("only_ids_not_found"):
        return NOT_EXTRACTED

    reached = "extracted"
    if by("written"):
        reached = "draft"
    tested = by("tested")
    if any(e.get("compiled") for e in tested):
        reached = "compiled"
    if any(e.get("real_pass") for e in tested):
        reached = "real_pass"
    if any(e.get("outcome") == "passed_verified" for e in by("task_done")):
        reached = "verified"
    return reached


def build_funnel(outcomes: list[CaseOutcome]) -> Funnel:
    """Aggregate case-runs into a per-stage survivor count (non-increasing by construction, FR-006)
    plus the NAMED cases that died at each stage. Off-ladder deaths (never extracted / infra error)
    are listed separately, counted as neither success nor proving-failure."""
    idx = {s: i for i, s in enumerate(STAGES)}
    survivors = {s: 0 for s in STAGES}
    casualties: dict = {s: [] for s in STAGES}
    off_ladder: dict = {NOT_EXTRACTED: [], ERROR: []}
    for o in outcomes:
        if o.stage in off_ladder:
            off_ladder[o.stage].append(o.case_id)
            # died before the ladder → a casualty at the very first stage
            casualties[STAGES[0]].append(o.case_id)
            continue
        reached = idx[o.stage]
        for i, s in enumerate(STAGES):
            if i <= reached:
                survivors[s] += 1
        if reached + 1 < len(STAGES):
            casualties[STAGES[reached + 1]].append(o.case_id)
    return Funnel(survivors=survivors, casualties=casualties, off_ladder=off_ladder)


# ── scoring: assemble the report (US3 - counts exactly passed_verified) ───────

def build_by_class(outcomes: list[CaseOutcome], class_of: dict[str, str]) -> dict[str, Interval]:
    """feature 037 G2 - a per-class credible interval, so a class-dependent wall (035 FR-018) is
    readable instead of averaged away. `class_of` maps case_id -> finding_class; case-runs whose class
    is empty/unknown are omitted (no spurious '' bucket). Same Jeffreys interval as the headline,
    computed on each class's own successes/trials. NEVER merged with the headline (that stays global)."""
    buckets: dict[str, list[CaseOutcome]] = {}
    for o in outcomes:
        cls = (class_of.get(o.case_id) or "").strip()
        if cls:
            buckets.setdefault(cls, []).append(o)
    out: dict[str, Interval] = {}
    for cls, os_ in sorted(buckets.items()):
        s = sum(1 for o in os_ if o.outcome == "passed_verified")
        out[cls] = credible_interval(s, len(os_))
    return out


def score(outcomes: list[CaseOutcome], config: RunConfig,
          class_of: dict[str, str] | None = None) -> Report:
    """Pure. Verified successes = case-runs whose outcome is EXACTLY `passed_verified` - nothing
    inferred, nothing model-judged (FR-007). Trials = all case-runs (every case is fix-bearing, so
    the denominator is exactly the loaded cases × N - there is no lead/fix-less case to exclude).

    feature 037 G2: when `class_of` is supplied, a per-class breakdown is added ALONGSIDE (never
    instead of) the headline interval - the class-stratified capability map (035 FR-018)."""
    trials = len(outcomes)
    successes = sum(1 for o in outcomes if o.outcome == "passed_verified")
    return Report(
        interval=credible_interval(successes, trials),
        funnel=build_funnel(outcomes),
        config=config,
        by_class=build_by_class(outcomes, class_of) if class_of else {},
    )


# ── the harness seam - the SOLE impure/expensive function (Decision 1) ────────

def run_case(case: Case, config: RunConfig, *, image: str | None = None, fork: bool = True,
             max_minutes: float = 30.0) -> list[CaseOutcome]:
    """Run the harness (BLACK BOX) N times for one case and parse each run's stdout events into a
    CaseOutcome. This is the ONLY function that touches a model/Docker/network and the ONLY thing the
    offline tests stub - everything else (interval, funnel, compare, score) is pure."""
    # feature 028: PIN the finding. Write the case's curated finding as a single-task file and feed
    # it via `--tasks-from` (dropping `--only`), so extraction is bypassed and the id AND text are
    # identical across all N runs - the eval measures the prover's variance, not extraction's. The
    # one task's id == finding_id == the `--fix-patch` id, so the fix attaches by construction.
    # The file is target material (carries the finding title/location) → external temp scratch,
    # cleaned up after the case's runs.
    task_fd, task_path = tempfile.mkstemp(prefix=f"proofcase-{case.case_id}-", suffix=".json")
    os.close(task_fd)
    Path(task_path).write_text(json.dumps([{
        "id": case.finding_id, "title": case.title,
        "location": case.location, "description": case.description,
    }]), encoding="utf-8")

    outcomes: list[CaseOutcome] = []
    try:
        for run_idx in range(config.n):
            argv = [
                sys.executable, str(_AGENT_ROOT / "scripts" / "poc_queue_runner.py"),
                "--project", str(case.target_path), "--report", str(case.report_path),
                "--tasks-from", task_path,
                "--fix-patch", f"{case.finding_id}={case.fix_path}",
                "--provider", config.provider, "--model", config.model,
            ]
            if config.scaffold:
                argv += ["--test-scaffold", config.scaffold]
            if config.example:
                argv += ["--example-poc", config.example]
            if image:
                argv += ["--image", image]
            if fork:
                argv += ["--fork"]
            argv += ["--max-minutes", str(max_minutes)]
            # HARD timeout on the child. `--max-minutes` is only a budget the harness checks in its
            # OWN loop - it cannot interrupt a wedged forge/Docker child, so without this a single
            # stuck run blocks the whole C×N eval forever, with no output and no partial results
            # (observed live: a via_ir container wedged for hours). On expiry the run is recorded
            # honestly in the existing off-ladder ERROR bucket - infra, neither success nor a
            # proving-failure - and the eval moves on. Margin over the harness's own budget so the
            # harness gets to stop itself first and report, and only a real wedge trips this.
            try:
                proc = subprocess.run(argv, capture_output=True, text=True,
                                      timeout=max_minutes * 60 + _HARNESS_TIMEOUT_MARGIN_S)
            except subprocess.TimeoutExpired:
                outcomes.append(CaseOutcome(
                    case_id=case.case_id, run_idx=run_idx, stage=ERROR,
                    outcome="harness_timeout", verify_reason="",
                ))
                continue
            events = _parse_events(proc.stdout)
            stage = _stage_of(events, case.finding_id)
            done = next((e for e in reversed(events) if e.get("event") == "task_done"), {})
            outcomes.append(CaseOutcome(
                case_id=case.case_id, run_idx=run_idx, stage=stage,
                outcome=str(done.get("outcome", "")), verify_reason=str(done.get("verify_reason", "")),
            ))
    finally:
        Path(task_path).unlink(missing_ok=True)   # ephemeral target-material scratch, always removed
    return outcomes


def _parse_events(stdout: str) -> list[dict]:
    out = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# ── rendering + result IO ─────────────────────────────────────────────────────

_DEV_CAVEAT = (
    "DEV SET - the harness/prompts were tuned on this case set. This measures REGRESSION/PROGRESS "
    "WITHIN the set, NOT absolute capability on smart contracts in general. A held-out set (not yet "
    "available) is required for a capability claim. Do not read a dev number as a capability number.")


def render(report: Report) -> str:
    iv, fn, cfg = report.interval, report.funnel, report.config
    lines = [
        f"proof-eval - case set '{cfg.case_set_id}'  model={cfg.model}  N={cfg.n}  "
        f"harness={cfg.harness_version}",
        "",
        f"VERIFIED fraction: {iv.successes}/{iv.trials} case-runs  "
        f"→ {int(iv.mass*100)}% credible interval [{iv.lo:.3f}, {iv.hi:.3f}]  "
        f"(width {iv.width:.3f})",
        f"  N={cfg.n}: {'wide - not yet decisive' if iv.width >= 0.33 else 'reasonably tight'}",
        "",
        "ATTRITION FUNNEL (survivors reaching each stage):",
    ]
    for s in STAGES:
        dead = fn.casualties.get(s, [])
        tail = f"   ↳ died here: {', '.join(dead)}" if dead else ""
        lines.append(f"  {s:<10} {fn.survivors[s]}{tail}")
    for bucket, ids in fn.off_ladder.items():
        if ids:
            lines.append(f"  [{bucket}] {', '.join(ids)}")
    lines += ["", _DEV_CAVEAT]
    return "\n".join(lines)


def write_result(root: Path, report: Report, name: str) -> Path:
    """Machine-readable result, written OUTSIDE the agent repo (FR-012/FR-015)."""
    out_dir = _external(root, "proof-bench root") / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{name}.json"
    dest.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return dest


# ── CLI (mirrors bench.py's run/compare subparsers) ───────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="proof-pipeline eval (feature 026)")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run the harness over a case set at N and score PROOF quality")
    r.add_argument("--root", default=os.environ.get("SR_PROOF_ROOT", ""),
                   help="external dataset root (default: $SR_PROOF_ROOT)")
    r.add_argument("--n", type=int, required=True, help="runs per case (Bayes@N)")
    r.add_argument("--provider", default="gemini")
    r.add_argument("--model", default="")
    r.add_argument("--scaffold", default="")
    r.add_argument("--example", default="")
    r.add_argument("--image", default=None)
    r.add_argument("--no-fork", action="store_true")
    r.add_argument("--harness-version", default=_harness_version())
    r.add_argument("--name", default="result", help="result file name (under <root>/results/)")

    c = sub.add_parser("compare", help="compare two result files honestly (overlap + config guard)")
    c.add_argument("a")
    c.add_argument("b")

    args = p.parse_args(argv)

    if args.command == "run":
        if not args.root:
            raise ProofBenchError("set SR_PROOF_ROOT (or --root) to the EXTERNAL dataset root")
        root = Path(args.root)
        cases = load_dataset(root)
        config = RunConfig(
            case_set_id=root.name, provider=args.provider, model=args.model,
            scaffold=args.scaffold, example=args.example,
            settings={"fork": not args.no_fork}, n=args.n, harness_version=args.harness_version)
        all_outcomes: list[CaseOutcome] = []
        for case in cases:
            all_outcomes += run_case(case, config, image=args.image, fork=not args.no_fork)
        class_of = {c.case_id: c.finding_class for c in cases if c.finding_class}
        report = score(all_outcomes, config, class_of=class_of or None)
        print(render(report))
        dest = write_result(root, report, args.name)
        print(f"\n[written] {dest}")
        return 0

    if args.command == "compare":
        ra = _load_report(Path(args.a))
        rb = _load_report(Path(args.b))
        print(json.dumps(compare(ra, rb), indent=2))
        return 0
    return 1


def _harness_version() -> str:
    try:
        out = subprocess.run(["git", "-C", str(_AGENT_ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _load_report(path: Path) -> Report:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    iv, fn, cf = d["interval"], d["funnel"], d["config"]
    by_class = {
        k: Interval(lo=v["lo"], hi=v["hi"], mass=v["mass"],
                    successes=v["successes"], trials=v["trials"])
        for k, v in d.get("by_class", {}).items()   # feature 037 G2: round-trips if present
    }
    return Report(
        interval=Interval(lo=iv["lo"], hi=iv["hi"], mass=iv["mass"],
                          successes=iv["successes"], trials=iv["trials"]),
        funnel=Funnel(survivors=fn["survivors"], casualties=fn["casualties"],
                      off_ladder=fn["off_ladder"]),
        config=RunConfig(**cf),
        by_class=by_class,
    )


if __name__ == "__main__":
    sys.exit(main())

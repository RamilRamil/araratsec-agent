"""Prover capability screen (feature 038) - a pre-registered, class-stratified capability map.

Turns the open cross-model question left by 037 ("which callable model clears which finding-class,
at what cost and latency") into a MEASURED map on the prover axis (Half B: finding→PoC→verify), the
only axis with an uncompromising falsifying oracle (`mutation_verify`). The deliverable is a Pareto
front over (capability × cost × latency) - NEVER a scalar "best model" (survival is class-dependent,
035 FR-018).

Reuse-first (research Decision 1): this module ONLY orchestrates + keeps records + assembles the map.
  - per-case attempt         → 037 `exploit_loop.run` (the real `attempt_fn` seam; injected here so
                               the cascade is target-free-testable and does not import the heavy loop)
  - battery load             → 028 `load_pinned_tasks` / `--tasks-from`
  - VERDICT                  → the byte-unchanged oracle path (`mutation_verify`/`_poc_defects`/fork/
                               035 gates) - this module adds NO new oracle (FR-009)
  - per-class Jeffreys        → `proof_bench` (G2), extended strictly additively with `dominates`/
    intervals + dominance      `resolve` (B9)

Three components:
  G3 multi-class battery   - pinned, class-tagged, fix-bearing findings (referenced by id/label only,
                             never target code - FR-016).
  G4 cost/latency axis     - $/case, $/pass, wall-clock per case → 3-D Pareto (FR-005/006).
  G5 three-stage cascade   - smoke (plumbing, N=1 + one retry) → trigger-screen (triggered?) →
                             Bayes@N over survivors only, cheap-first (FR-001/002/018).

Honesty load-bearing:
  - `resolved`/`underpowered@N` are PAIRWISE (SC-008); a single separated pair never marks a class
    resolved. A class with zero separated pairs is `underpowered@N`.
  - Decision 8: while a class has one fix-bearing finding (`cases_per_class == 1`), the axis is
    `representative-finding capability`, cells/pairs carry `single-item@class`; a `resolved`/dominant
    label is scoped to that finding, NEVER read as a class-level claim.
  - The frontier is a single OUT-OF-CASCADE ceiling point - no interval, excluded from dominance and
    the Pareto (FR-011/020, relay wall).
  - Pre-registration is append-only under `<target>/audit/`; adding a model is a NEW entry, never a
    re-open (anti subject-shopping - FR-007/008).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Allow `python scripts/capability_screen.py ...` (operator CLI) as well as `import
# scripts.capability_screen` (tests/subprocess): put the repo root on the path when run unpackaged.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.proof_bench as pb
from scripts.proof_bench import Interval, credible_interval, dominates, resolve
from scripts.solidity_utils import POC_SUBDIR  # feature 040: the per-run log lives under <project>/<POC_SUBDIR>/_runs

_AGENT_ROOT = Path(__file__).resolve().parents[1]

# The trigger-screen bar and the Bayes@N transient-retry cap. A transient (timeout/503) is retried a
# bounded number of times so it never silently scores as a capability miss (FR-014); past the cap it
# is recorded as transient and excluded from the denominator, never counted as a verified 0.
_TRANSIENT_RETRY_CAP = 3
# Smoke is a plumbing/crash-check with ONE allowed retry (FR-018) - a capable model that fails a
# single N=1 draw under bimodal reproducibility must not be dropped as a capability failure.
_SMOKE_RETRY = 1
# T025: the trigger-screen needs its OWN, SMALLER cap. A screen attempt is the longest in the cascade
# (a full fork loop under the 1800s subprocess ceiling), so reusing the Bayes cap of 3 could burn ~2h
# per cell on a persistently-broken candidate. One retry separates a flake from a persistent failure;
# past it the honest record is `screen="unavailable"` - which is precisely NOT a capability claim, so
# there is nothing to gain by paying for more retries.
_SCREEN_TRANSIENT_RETRY = 1


class CapabilityScreenError(Exception):
    """Bad pre-registration / battery / enforcement violation - always loud, never a silent skip."""


def oracle_verdict_hash() -> str:
    """A6/SC-005 - a hash over the BYTE-UNCHANGED verdict functions (`mutation_verify`, `_poc_defects`
    in `poc_queue_runner`). This module imports and CALLS them; it never redefines them (grep this
    file: no `def mutation_verify`). A test pins this hash so any edit to the verdict path is caught,
    and asserts the screen carries no shadowing definition (FR-009). Lazy import - the runner is heavy
    and only needed at the operator step, not to assemble a map from fixtures."""
    import inspect

    import scripts.poc_queue_runner as runner
    src = inspect.getsource(runner.mutation_verify) + "\n" + inspect.getsource(runner._poc_defects)
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


# ── entities (data-model.md) ──────────────────────────────────────────────────

@dataclass(frozen=True)
class Candidate:
    """A callable model under screen. `callable_via_harness=False` ⇒ reference-only (the frontier,
    relay wall): excluded from every cascade stage and from the interval dominance rule (FR-011/020)."""
    id: str
    cost_class: str = "cheap"          # cheap / mid - drives cheap-first ordering (A5)
    callable_via_harness: bool = True

    # cheap-first: cheap before mid; stable by id within a class
    _ORDER = {"cheap": 0, "mid": 1, "expensive": 2}

    @property
    def order_key(self) -> tuple[int, str]:
        return (self._ORDER.get(self.cost_class, 99), self.id)


@dataclass(frozen=True)
class BatteryCase:
    """A pinned, fix-bearing finding - referenced by pinned id / dev-set label only (NO target code,
    FR-016). `finding_class` MUST be a member of the pre-registered closed enum (FR-019)."""
    case_id: str
    finding_class: str
    has_fix_diff: bool = True


@dataclass(frozen=True)
class AttemptResult:
    """One per-case attempt through the injected seam. In the real path `attempt_fn` runs the 037
    loop and asks the byte-unchanged oracle for `verified`; in tests it is scripted. `produced` is the
    smoke/plumbing signal (the loop emitted runnable code at all); `triggered` is the forge PASS
    (trigger-screen bar); `verified` is the SOLE oracle verdict (Bayes@N numerator)."""
    produced: bool
    triggered: bool
    verified: bool
    tokens: int = 0
    seconds: float = 0.0
    transient: bool = False
    # T022/FR-021: WHY this attempt is transient, when the cause is host/sandbox infra rather than a
    # provider one - "oom" (container/solc OOM-kill), "killed" (runner process signalled). Empty for a
    # normal (capability) result or a provider transient. Recorded in the run-log so a masked infra
    # failure is diagnosable, and it takes PRIORITY over the runner's outcome string (see
    # `signals_to_result`): an OOM that the runner swallowed into a non-compiling build MUST NOT score
    # as a capability miss.
    infra_cause: str = ""


@dataclass
class CascadeStageResult:
    """Per candidate × class outcome across the three stages (data-model)."""
    candidate: str
    finding_class: str
    smoke: str = "pass"                 # "pass" | "plumbing_fail" | "infra" (never a capability verdict)
    # T025/FR-014: "pass" | "unavailable". `unavailable` means the trigger-screen never produced a
    # usable answer (transient past the retry cap) - so `triggered=False` on such a cell is NOT a
    # measured capability fact and MUST NOT be published as one (see `build_map`).
    screen: str = "pass"
    triggered: bool = False
    verified_k: int = 0
    n: int = 0
    transient_failures: int = 0
    interval: Interval | None = None    # survivors only; None when not_triggered / plumbing_fail
    single_item: bool = False           # Decision 8 - set while cases_per_class == 1

    def to_dict(self) -> dict:
        d = {
            "candidate": self.candidate, "finding_class": self.finding_class,
            "smoke": self.smoke, "screen": self.screen, "triggered": self.triggered,
            "verified_k": self.verified_k, "n": self.n,
            "transient_failures": self.transient_failures,
            "single_item": self.single_item,
        }
        if self.interval is not None:
            d["interval"] = self.interval.to_dict()
        return d


@dataclass
class CostLatencyRecord:
    """Per candidate × class cost/latency (FR-005). `$/pass` is undefined (None) at zero passes -
    reported honestly, never as 0 or ∞ silently (Decision 4)."""
    candidate: str
    finding_class: str
    tokens: int = 0
    seconds: float = 0.0
    passes: int = 0
    usd_per_case: float = 0.0
    usd_per_pass: float | None = None

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate, "finding_class": self.finding_class,
            "tokens": self.tokens, "seconds": round(self.seconds, 3),
            "passes": self.passes, "usd_per_case": round(self.usd_per_case, 6),
            "usd_per_pass": (None if self.usd_per_pass is None
                             else round(self.usd_per_pass, 6)),
        }


@dataclass(frozen=True)
class PairResolution:
    """The unit that makes the map actionable (FR-017, SC-008/010). Resolution is PAIRWISE - a class
    is never 'resolved' by a single separated pair. `single_item` (Decision 8) scopes a resolution to
    the one finding while `cases_per_class == 1`."""
    finding_class: str
    a: str
    b: str
    status: str                        # "resolved" | "unresolved@N"
    dominant: str | None
    single_item: bool = False

    def to_dict(self) -> dict:
        return {"finding_class": self.finding_class, "a": self.a, "b": self.b,
                "status": self.status, "dominant": self.dominant,
                "single_item": self.single_item}


# ── pre-registration (contract prereg.md - C1..C6) ────────────────────────────

_FROZEN_FIELDS = (
    "candidates", "class_enum", "per_stage_thresholds", "N_by_class", "cases_per_class",
    "credible_level", "dominance_rule", "pinned_bench_id", "price_table",
)


def content_hash(record: dict) -> str:
    """Deterministic hash over the FROZEN fields only (not `ts`/`content_hash`) - canonical JSON so a
    byte-identical frozen record always hashes the same, and any tamper on a stored entry is detected
    on load (C4)."""
    frozen = {k: record.get(k) for k in _FROZEN_FIELDS}
    blob = json.dumps(frozen, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _external(p: Path) -> Path:
    """Refuse a records path inside the agent repo - the pre-registration + battery live under
    `<target>/audit/`, outside the repo (FR-016), same discipline as proof_bench/bench."""
    r = Path(p).expanduser().resolve()
    if r == _AGENT_ROOT or _AGENT_ROOT in r.parents:
        raise CapabilityScreenError(
            f"pre-registration path must be EXTERNAL to the agent repo (under <target>/audit/), got: {r}")
    return r


def make_prereg(*, candidates: list[Candidate], class_enum: list[str],
                n_by_class: dict[str, int], cases_per_class: int, credible_level: float,
                pinned_bench_id: str, price_table: dict[str, float],
                per_stage_thresholds: dict | None = None, ts: str = "") -> dict:
    """Assemble a frozen pre-registration record dict (not yet written). `content_hash` is computed
    over the frozen fields; `ts` is metadata (excluded from the hash)."""
    record = {
        "ts": ts,
        "candidates": [{"id": c.id, "cost_class": c.cost_class,
                        "callable_via_harness": c.callable_via_harness} for c in candidates],
        "class_enum": list(class_enum),
        "per_stage_thresholds": per_stage_thresholds or {
            "smoke_retry": _SMOKE_RETRY, "trigger_bar": "triggered"},
        "N_by_class": dict(n_by_class),
        "cases_per_class": cases_per_class,
        "credible_level": credible_level,
        "dominance_rule": "interval non-overlap at credible_level",
        "pinned_bench_id": pinned_bench_id,
        "price_table": dict(price_table),
    }
    record["content_hash"] = content_hash(record)
    return record


def write_prereg(path: Path, record: dict) -> Path:
    """Append ONE record as a JSONL line under `<target>/audit/` (C3 append-only). Each `prereg`
    invocation appends a NEW entry; a prior entry is never rewritten. A record whose `content_hash`
    is stale/absent is recomputed so the file is always internally consistent."""
    path = _external(path)
    record = dict(record)
    record["content_hash"] = content_hash(record)          # canonicalize
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def load_prereg(path: Path) -> list[dict]:
    """Load all entries, verifying each entry's stored `content_hash` matches a recompute over its
    frozen fields (C4 tamper detection). A mismatch is a LOUD error - a mutated prior entry must never
    pass silently."""
    path = _external(path)
    if not path.is_file():
        raise CapabilityScreenError(f"no pre-registration record at {path}")
    records = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        want = content_hash(rec)
        if rec.get("content_hash") != want:
            raise CapabilityScreenError(
                f"{path} entry {i}: content_hash mismatch (frozen fields were mutated after write) - "
                f"stored={rec.get('content_hash')!r} recomputed={want!r}")
        records.append(rec)
    return records


def active_record(records: list[dict], *, bench_id: str) -> dict:
    """The LATEST entry for a given pinned bench (a late-added candidate appends a new entry; the most
    recent one is the active subject). No matching entry ⇒ loud (C1)."""
    matches = [r for r in records if r.get("pinned_bench_id") == bench_id]
    if not matches:
        raise CapabilityScreenError(f"no active pre-registration entry for bench {bench_id!r}")
    return matches[-1]


def enforce_subject(record: dict, candidate_id: str) -> None:
    """C2 - a scored subject MUST be in the active record's candidate list."""
    ids = {c["id"] for c in record.get("candidates", [])}
    if candidate_id not in ids:
        raise CapabilityScreenError(
            f"candidate {candidate_id!r} is not in the active pre-registration record - "
            f"score only registered subjects (add it as a NEW prereg entry to screen it)")


def enforce_class(record: dict, finding_class: str) -> None:
    """C5 - a battery case's class MUST be inside the closed pre-registered enum (FR-019)."""
    if finding_class not in set(record.get("class_enum", [])):
        raise CapabilityScreenError(
            f"finding_class {finding_class!r} is outside the closed pre-registered enum "
            f"{record.get('class_enum')!r} - labels cannot drift between runs (FR-010/019)")


# ── the cascade (contract cascade.md - A1..A7) ────────────────────────────────

def _bayes_attempt(attempt_fn, candidate_id: str, case_id: str, out: CascadeStageResult) -> AttemptResult:
    """One Bayes@N attempt with bounded transient retry (A4): a timeout/503 increments
    `transient_failures` and is retried, never scored as a verified miss. Past the cap the attempt is
    returned transient so the caller EXCLUDES it from the denominator (not a capability 0)."""
    res = attempt_fn(candidate_id, case_id, "bayes")
    tries = 0
    while res.transient and tries < _TRANSIENT_RETRY_CAP:
        out.transient_failures += 1
        tries += 1
        res = attempt_fn(candidate_id, case_id, "bayes")
    if res.transient:
        out.transient_failures += 1
    return res


def _screen_attempt(attempt_fn, candidate_id: str, case_id: str,
                    out: CascadeStageResult) -> AttemptResult:
    """T025 - one trigger-screen attempt with bounded transient retry (FR-014).

    Before this existed the trigger-screen was the ONLY stage that did not inspect `transient`: smoke
    routes a transient through `produced=False` → retry → `plumbing_fail`, and Bayes@N skips it with
    `continue`, but the screen took `scr.triggered` at face value. A timeout/503/`draft_failed` there
    left `triggered=False` and logged `not_triggered` - publishing an infra failure as a measured
    capability verdict. (Observed live 2026-07-27: a screen attempt hit the 1800s timeout and the
    shipped map recorded `"triggered": false` for that cell.)

    Retries are capped by `_SCREEN_TRANSIENT_RETRY`, not the Bayes cap - see the constant. Past the
    cap the transient result is RETURNED transient so the caller marks the cell `unavailable` instead
    of concluding anything about the model."""
    res = attempt_fn(candidate_id, case_id, "screen")
    tries = 0
    while res.transient and tries < _SCREEN_TRANSIENT_RETRY:
        out.transient_failures += 1
        tries += 1
        res = attempt_fn(candidate_id, case_id, "screen")
    if res.transient:
        out.transient_failures += 1
    return res


def run_cascade(*, record: dict, battery: list[BatteryCase], candidates: list[Candidate],
                attempt_fn, price_table: dict[str, float] | None = None,
                log=None) -> tuple[list[CascadeStageResult], list[CostLatencyRecord]]:
    """Drive smoke → trigger-screen → Bayes@N per candidate × class, cheap-first.

    `attempt_fn(candidate_id, case_id, stage) -> AttemptResult` is the SOLE expensive/impure seam - it
    runs the 037 loop and asks the byte-unchanged oracle for the verdict in the real path, and is
    scripted in tests. No model turn takes a privileged/write action (FR-015): the seam only
    runs/inspects a PoC.

    Cheap-first + no-waste (A1/A5/SC-002): within a class, ALL candidates' smoke+trigger-screen run
    before ANY Bayes@N, and a `not_triggered` (or `plumbing_fail`) cell spends ZERO Bayes@N attempts.
    `callable_via_harness=False` candidates run NO stage (A7)."""
    log = log or (lambda _e: None)
    price_table = price_table or record.get("price_table", {})
    cases_per_class = int(record.get("cases_per_class", 1))
    single = cases_per_class == 1                        # Decision 8 scope flag
    n_by_class = record.get("N_by_class", {})

    # group the battery by class (skip unlabelled - no junk '' bucket; edge case)
    by_class: dict[str, list[BatteryCase]] = {}
    for bc in battery:
        if not bc.finding_class.strip():
            continue
        enforce_class(record, bc.finding_class)          # C5 - closed enum
        by_class.setdefault(bc.finding_class, []).append(bc)

    active = sorted((c for c in candidates if c.callable_via_harness), key=lambda c: c.order_key)
    for c in candidates:
        enforce_subject(record, c.id)                    # C2 - every subject registered

    stage_results: list[CascadeStageResult] = []
    cost_records: list[CostLatencyRecord] = []

    for cls in sorted(by_class):
        cases = by_class[cls]
        n = int(n_by_class.get(cls, 0))
        # PHASE A - smoke + trigger-screen for every candidate (cheap-first), before any Bayes@N.
        survivors: list[Candidate] = []
        pending: dict[str, CascadeStageResult] = {}
        cost: dict[str, CostLatencyRecord] = {}
        for cand in active:
            res_cell = CascadeStageResult(candidate=cand.id, finding_class=cls,
                                          n=n, single_item=single)
            cl = CostLatencyRecord(candidate=cand.id, finding_class=cls)
            pending[cand.id] = res_cell
            cost[cand.id] = cl

            # stage 1 - smoke (plumbing/crash-check, N=1 + one retry). NOT a capability filter.
            smoke = attempt_fn(cand.id, cases[0].case_id, "smoke")
            _accrue(cl, smoke)
            if not smoke.produced:
                retry = attempt_fn(cand.id, cases[0].case_id, "smoke")
                _accrue(cl, retry)
                smoke = retry
            if not smoke.produced:
                # T022/FR-021: distinguish a host-resource failure (OOM) from a genuine plumbing
                # failure. Both are excluded from triggered/verified, but labelling an OOM
                # `plumbing_fail` would imply the MODEL's output was un-runnable when the host simply
                # ran out of memory - the exact instrument-vs-model confound this work exists to kill.
                if smoke.infra_cause:
                    res_cell.smoke = "infra"
                    log({"event": "smoke_infra", "candidate": cand.id, "class": cls,
                         "cause": smoke.infra_cause})
                else:
                    res_cell.smoke = "plumbing_fail"     # A2 - excluded from triggered/verified
                    log({"event": "smoke_plumbing_fail", "candidate": cand.id, "class": cls})
                continue

            # stage 2 - trigger-screen (bar = triggered, NOT verified). Trigger on ANY class case.
            # T025/FR-014: a transient here is NOT evidence about the model. It is retried (bounded),
            # and if it never resolves the case yields NO verdict - we fall through to the next case
            # and, if nothing triggers, the cell is `unavailable` rather than `not_triggered`.
            # Transients are also excluded from cost/latency accrual, matching the Bayes stage: the
            # axes measure model work, not infra failure.
            triggered = False
            screen_unavailable = False
            for bc in cases:
                scr = _screen_attempt(attempt_fn, cand.id, bc.case_id, res_cell)
                if scr.transient:
                    screen_unavailable = True
                    continue
                _accrue(cl, scr)
                if scr.triggered:
                    triggered = True
                    break
            res_cell.triggered = triggered
            if triggered:
                survivors.append(cand)                    # a real PASS outranks a sibling transient
            elif screen_unavailable:
                res_cell.screen = "unavailable"           # never a capability verdict (FR-014)
                log({"event": "screen_unavailable", "candidate": cand.id, "class": cls})
            else:
                log({"event": "not_triggered", "candidate": cand.id, "class": cls})

        # PHASE B - Bayes@N over survivors ONLY (A1/SC-002). Honest zero-survivors (FR-013).
        if not survivors:
            log({"event": "zero_survivors", "class": cls})
        for cand in sorted(survivors, key=lambda c: c.order_key):
            res_cell = pending[cand.id]
            cl = cost[cand.id]
            verified_k = 0
            trials = 0
            for bc in cases:
                for _ in range(n):
                    res = _bayes_attempt(attempt_fn, cand.id, bc.case_id, res_cell)
                    if res.transient:
                        continue                          # A4 - excluded, never a verified 0
                    _accrue(cl, res)
                    trials += 1
                    if res.verified:
                        verified_k += 1
            res_cell.verified_k = verified_k
            res_cell.n = trials
            res_cell.interval = credible_interval(
                verified_k, trials, mass=float(record.get("credible_level", 0.95)))
            cl.passes = verified_k

        for cand in active:
            _finalize_cost(cost[cand.id], price_table)
            stage_results.append(pending[cand.id])
            cost_records.append(cost[cand.id])

    return stage_results, cost_records


def _accrue(cl: CostLatencyRecord, res: AttemptResult) -> None:
    if res.transient:
        return
    cl.tokens += res.tokens
    cl.seconds += res.seconds


def _finalize_cost(cl: CostLatencyRecord, price_table: dict[str, float]) -> None:
    """Derive $/case and $/pass from the PINNED price table (Decision 4). `$/pass` undefined at zero
    passes - honest None, never a silent 0/∞."""
    price = float(price_table.get(cl.candidate, 0.0))    # USD per 1k tokens (pinned)
    cl.usd_per_case = (cl.tokens / 1000.0) * price
    cl.usd_per_pass = None if cl.passes == 0 else cl.usd_per_case / cl.passes


# ── T008 live wire: the real attempt_fn (037 loop + byte-unchanged oracle) ────
#
# Reuse-first (Decision 1): we do NOT re-implement drafting/verify here. Each attempt shells out to
# the EXISTING `poc_queue_runner` for one (model, case) and reads its per-task verdict off stdout
# (the runner prints one JSON event per line). The verdict oracle stays byte-unchanged (FR-009).

# A real forge PASS happened (`real_pass` in the runner). `passed_verified` additionally survived the
# mutation_verify falsification; `unverified_pass`/`passed_unchecked` PASSed but were not (or could not
# be) falsified. Trigger-screen bar = triggered = any of these three. Vacuous/compiled-only never
# count as triggered.
_TRIGGERED_OUTCOMES = frozenset({"passed_verified", "unverified_pass", "passed_unchecked"})
_VERIFIED_OUTCOME = "passed_verified"
# Infra/transport failures the RUNNER reports as an outcome (poc_queue_runner:2428/2432) - NOT a
# capability miss. Scored transient (excluded from the Bayes denominator, retried), never a verified 0
# (FR-014). `draft_failed` (a MODEL_ERRORS network/API abort) is likewise transient.
_TRANSIENT_OUTCOMES = frozenset({"sandbox_unavailable", "run_error", "draft_failed"})

# T022/FR-021: a host/sandbox OOM-kill is NOT a capability miss, but the runner SWALLOWS it into a
# non-compiling build and reports a capability-looking outcome (`exhausted`/`compile_only_defective`/
# `compiled`), so guarding on the outcome string alone misses it. Detect it at its true source - the
# runner's emitted `tested` events: a container SIGKILL surfaces as `exit_code == 137` (128+9) and/or
# an OOM signature in the compiler/forge output. Markers are deliberately SPECIFIC (no bare "Killed",
# which is too noisy) so a genuine build failure is never mislabelled infra.
_OOM_EXIT_CODE = 137
_OOM_MARKERS = ("signal: 9", "sigkill", "oomkilled", "out of memory", "std::bad_alloc",
                "cannot allocate memory")


def _looks_like_oom(exit_code, *tails: str) -> bool:
    if isinstance(exit_code, (int, float)) and int(exit_code) == _OOM_EXIT_CODE:
        return True
    blob = " ".join(t for t in tails if t).lower()
    return any(m in blob for m in _OOM_MARKERS)


def parse_runner_events(stdout: str, finding_id: str) -> dict:
    """Pure/offline-testable: fold the runner's JSONL stdout into the signals for one finding id.
    Returns {outcome, saw_tested, elapsed_s, tokens, has_task_done, infra_cause}. A missing `task_done`
    (crash / provider error / timeout upstream) leaves has_task_done=False → the caller scores it
    transient, never a verified 0 (FR-014). `infra_cause` is set to "oom" when a `tested` event shows
    a container OOM-kill (T022/FR-021) - the runner may still emit a capability-looking `task_done`
    afterwards, so this signal is folded independently and takes priority downstream."""
    outcome = ""
    saw_tested = False
    elapsed_s = 0.0
    tokens = 0
    has_task_done = False
    infra_cause = ""
    run_id = ""
    fid = finding_id.strip().lower()
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not run_id:                                       # feature 040: the runner stamps run_id
            run_id = str(ev.get("run_id", "") or "")         # on EVERY event; grab the first one
        if str(ev.get("finding_id", "")).strip().lower() != fid:
            # usage/token events may not carry a finding_id - still scrape tokens best-effort
            for k in ("total_tokens", "tokens", "completion_tokens", "prompt_tokens"):
                v = ev.get(k)
                if isinstance(v, (int, float)):
                    tokens += int(v)
            continue
        etype = ev.get("event")
        if etype == "tested":
            saw_tested = True
            if not infra_cause and _looks_like_oom(
                    ev.get("exit_code"), str(ev.get("stderr_tail", "")), str(ev.get("stdout_tail", ""))):
                infra_cause = "oom"
        elif etype == "task_done":
            has_task_done = True
            outcome = str(ev.get("outcome", ""))
            elapsed_s = float(ev.get("elapsed_s", 0.0) or 0.0)
        for k in ("total_tokens", "tokens", "completion_tokens", "prompt_tokens"):
            v = ev.get(k)
            if isinstance(v, (int, float)):
                tokens += int(v)
    return {"outcome": outcome, "saw_tested": saw_tested, "elapsed_s": elapsed_s,
            "tokens": tokens, "has_task_done": has_task_done, "infra_cause": infra_cause,
            "run_id": run_id}


def persist_case_log(runs_dir: Path, stdout: str, stderr: str, *, run_id: str,
                     model: str, case_id: str, stage: str) -> Path:
    """Persist ONE spawned per-case runner log so a post-hoc analysis can see exactly where a model
    stumbled (feature 040 US1; closes 038 T027). Named by the runner's own `run_id` under `_runs/`
    (the log-events.md scheme) - the same file the runner streams to disk, re-persisted from the
    screen's captured stdout so it survives even a partial write. On an OPAQUE no-start exit (the
    subprocess died before emitting any attributed event, so there is no run_id) a deterministic
    fallback id keyed on (model,case,stage)+a short content hash keeps even that empty exit
    traceable, with its stderr tail recorded as a trailing `screen_capture` line."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    rid = run_id or ("nostart-" + hashlib.sha256(
        f"{model}|{case_id}|{stage}|{stderr[-500:]}".encode()).hexdigest()[:12])
    path = runs_dir / f"{rid}.jsonl"
    body = stdout if (not stdout or stdout.endswith("\n")) else stdout + "\n"
    if not run_id:  # opaque exit: nothing attributed on stdout - preserve the stderr so it is diagnosable
        body += json.dumps({"event": "screen_capture", "model": model, "case": case_id,
                            "stage": stage, "no_run_id": True,
                             "stderr_tail": stderr[-1000:].strip()}) + "\n"
    path.write_text(body, encoding="utf-8")
    return path


def signals_to_result(parsed: dict) -> AttemptResult:
    """Pure/offline-testable: map parsed runner signals → AttemptResult. No `task_done` ⇒ transient
    (couldn't measure), NOT a verified miss (FR-014).

    T022/FR-021: an `infra_cause` (a host/sandbox OOM the runner swallowed) takes PRIORITY over the
    outcome string - checked FIRST, before `has_task_done` and before the outcome branches - so an OOM
    that surfaced as a non-compiling build is scored transient, never as `produced/not-triggered`."""
    if parsed.get("infra_cause"):                            # host-resource failure ≠ capability miss
        return AttemptResult(produced=False, triggered=False, verified=False,
                             tokens=parsed["tokens"], seconds=parsed["elapsed_s"],
                             transient=True, infra_cause=parsed["infra_cause"])
    if not parsed["has_task_done"]:
        return AttemptResult(produced=False, triggered=False, verified=False,
                             tokens=parsed["tokens"], seconds=parsed["elapsed_s"], transient=True)
    outcome = parsed["outcome"]
    if outcome in _TRANSIENT_OUTCOMES:                       # infra/API failure ≠ capability miss
        return AttemptResult(produced=False, triggered=False, verified=False,
                             tokens=parsed["tokens"], seconds=parsed["elapsed_s"], transient=True)
    produced = parsed["saw_tested"] or outcome in _TRIGGERED_OUTCOMES or outcome in (
        "compiled", "vacuous_pass", "reverted_exhausted", "compile_only_defective", "exhausted")
    return AttemptResult(
        produced=produced,
        triggered=outcome in _TRIGGERED_OUTCOMES,
        verified=outcome == _VERIFIED_OUTCOME,
        tokens=parsed["tokens"],
        seconds=parsed["elapsed_s"],
        transient=False)


def make_live_attempt_fn(*, project: Path, report: Path, tasks_from: Path,
                         image: str | None = None, timeout_s: int = 1800,
                         smoke_budget_calls: int = 1, smoke_budget_min: float = 3.0,
                         loop_budget_calls: int = 8, loop_budget_min: float = 15.0,
                         runlog=None, python_exe: str | None = None):
    """Build the real `attempt_fn(model, case_id, stage)` for `run_cascade`. Each call runs ONE
    independent replicate via `poc_queue_runner` (037 agentic loop) and reads the byte-unchanged
    oracle's verdict off stdout. Stage-aware economy: `smoke` is a CHEAP plumbing check - the agentic
    loop budget is capped low (`--loop-budget-calls/-min`), because `--attempts` does NOT bound the
    agentic loop (it runs its full call/wall budget regardless) so a full-budget smoke would cost the
    same ~15 min as a real proof attempt. `screen`/`bayes` run with `--fork` (a real PASS is the only
    bar) at the full loop budget. The subprocess inherits os.environ - the operator has exported ONLY
    OPENROUTER_API_KEY + MAINNET_RPC_URL into it (never the whole .env)."""
    py = python_exe or sys.executable
    runlog = runlog or (lambda _e: None)
    runs_dir = project / POC_SUBDIR / "_runs"   # feature 040: retained per-case logs (closes 038 T027)

    def attempt_fn(model: str, case_id: str, stage: str) -> AttemptResult:
        cmd = [py, "-m", "scripts.poc_queue_runner",
               "--project", str(project), "--report", str(report),
               "--tasks-from", str(tasks_from), "--only", case_id,
               "--provider", "openrouter", "--model", model, "--agentic-loop"]
        if image:
            cmd += ["--image", image]
        if stage == "smoke":
            # cheap plumbing: no fork, and a MINIMAL loop budget (attempts alone doesn't bound it)
            cmd += ["--attempts", "1",
                    "--loop-budget-calls", str(smoke_budget_calls),
                    "--loop-budget-min", str(smoke_budget_min)]
        else:
            cmd += ["--fork",                                 # real PASS bar (auto require_pass)
                    "--loop-budget-calls", str(loop_budget_calls),
                    "--loop-budget-min", str(loop_budget_min)]
        try:
            proc = subprocess.run(cmd, cwd=str(_AGENT_ROOT), env=os.environ.copy(),
                                  capture_output=True, text=True, timeout=timeout_s)
            stdout = proc.stdout
        except subprocess.TimeoutExpired as e:
            stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
            err = (e.stderr or "") if isinstance(e.stderr, str) else ""
            parsed = parse_runner_events(stdout, case_id)
            # Feature 040 US1: persist even a timed-out run's captured log so the stall is analysable.
            persist_case_log(runs_dir, stdout, err, run_id=parsed.get("run_id", ""),
                             model=model, case_id=case_id, stage=stage)
            runlog({"event": "attempt_timeout", "model": model, "case": case_id, "stage": stage,
                    "run_id": parsed.get("run_id", "")})
            parsed["has_task_done"] = False                   # timed out → transient
            return signals_to_result(parsed)
        parsed = parse_runner_events(stdout, case_id)
        # Feature 040 US1: persist the full captured per-case log under _runs/<run_id>.jsonl so a
        # post-hoc analysis can see exactly where this (model, case, stage) stumbled (closes 038 T027).
        persist_case_log(runs_dir, stdout, proc.stderr or "", run_id=parsed.get("run_id", ""),
                         model=model, case_id=case_id, stage=stage)
        # T022/FR-021: if the runner PROCESS ITSELF was signal-killed (137 = 128+9 SIGKILL, or a
        # negative code on POSIX), that is a host-resource kill of the whole subprocess - infra, not a
        # capability miss. This complements the in-stream OOM detection (which catches the more common
        # case where only the docker child was OOM'd and the runner exited 0).
        if not parsed.get("infra_cause") and (proc.returncode == _OOM_EXIT_CODE or proc.returncode < 0):
            parsed["infra_cause"] = "killed"
        res = signals_to_result(parsed)
        event = {"event": "attempt", "model": model, "case": case_id, "stage": stage,
                 "outcome": parsed["outcome"], "produced": res.produced,
                 "triggered": res.triggered, "verified": res.verified,
                 "transient": res.transient, "seconds": res.seconds, "tokens": res.tokens,
                 "returncode": proc.returncode, "run_id": parsed.get("run_id", "")}
        if res.infra_cause:
            event["infra_cause"] = res.infra_cause
        # T027: a non-productive exit (no task_done) is currently opaque - the subprocess stdout is not
        # persisted, so an instant rc=0 empty exit (observed for one candidate×case) cannot be
        # diagnosed after the fact. Capture a short stderr tail on such exits so the next occurrence is
        # traceable, without bloating the log on the normal path.
        if not parsed["has_task_done"]:
            tail = (proc.stderr or "")[-500:].strip()
            if tail:
                event["stderr_tail"] = tail
        runlog(event)
        return res

    return attempt_fn


# ── map assembly: pairwise resolution + underpowered@N (B1/B2/B7) ─────────────

def build_pairs(stage_results: list[CascadeStageResult],
                credible_level: float) -> tuple[list[PairResolution], list[str]]:
    """Every candidate PAIR in every class → `resolved`/`unresolved@N` (B1). A class with ZERO
    separated pairs is `underpowered@N` (B2). A single separated pair NEVER marks the class resolved
    (SC-008). Only cells with an interval (trigger-screen survivors) participate - a `not_triggered`
    or `plumbing_fail` cell has no interval and forms no pair."""
    by_class: dict[str, list[CascadeStageResult]] = {}
    for r in stage_results:
        if r.interval is not None:
            by_class.setdefault(r.finding_class, []).append(r)

    pairs: list[PairResolution] = []
    underpowered: list[str] = []
    for cls in sorted(by_class):
        cells = sorted(by_class[cls], key=lambda r: r.candidate)
        separated = 0
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                a, b = cells[i], cells[j]
                status = resolve(a.interval, b.interval)
                dominant = None
                if status == "resolved":
                    separated += 1
                    dominant = a.candidate if dominates(a.interval, b.interval) else b.candidate
                pairs.append(PairResolution(
                    finding_class=cls, a=a.candidate, b=b.candidate,
                    status=status, dominant=dominant,
                    single_item=a.single_item or b.single_item))
        # a class that COULD have a pair but separated none is underpowered@N (B2)
        if len(cells) >= 2 and separated == 0:
            underpowered.append(cls)
    return pairs, underpowered


# ── 3-D Pareto (B5/B6/B8, Decision 6) ─────────────────────────────────────────

def _cap_relation(cls: str, a: str, b: str, pairs: list[PairResolution]) -> str:
    """Capability relation of A vs B within a class from the pairwise table: 'a'/'b' if resolved in
    that direction, else 'incomparable' (overlapping intervals - Decision 6)."""
    for p in pairs:
        if p.finding_class != cls or p.status != "resolved":
            continue
        if {p.a, p.b} == {a, b}:
            return "a" if p.dominant == a else "b"
    return "incomparable"


def pareto_nondominated(stage_results: list[CascadeStageResult],
                        cost_by: dict[tuple[str, str], CostLatencyRecord],
                        pairs: list[PairResolution]) -> list[dict]:
    """The non-dominated set under the 3-D partial order (interval capability × cost × latency,
    Decision 6). A dominates B iff A is non-worse on cost AND latency AND A's capability interval
    dominates B's; a capability-INCOMPARABLE pair (overlapping intervals) is incomparable in 3-D too -
    both may stay non-dominated (B5), which honestly enlarges the set rather than forcing an order.
    Only interval-bearing (trigger-screen-survivor) cells enter; the frontier ceiling never does
    (B8)."""
    cells = [r for r in stage_results if r.interval is not None]
    nondom = []
    for a in cells:
        ca = cost_by.get((a.candidate, a.finding_class))
        dominated = False
        for b in cells:
            if b is a or b.finding_class != a.finding_class:
                continue
            cb = cost_by.get((b.candidate, b.finding_class))
            if ca is None or cb is None:
                continue
            # capability relation of a vs b: 'a' (a dominates), 'b' (b dominates), 'incomparable'.
            # b can dominate a in 3-D ONLY when b's interval dominates a's (capability strictly
            # better) - overlapping/incomparable capability is NOT "non-worse", so it can never let
            # a cheaper/faster b dominate an overlapping a (Decision 6 / B5).
            rel = _cap_relation(a.finding_class, a.candidate, b.candidate, pairs)
            if rel != "b":
                continue
            # b is capability-dominant; it dominates a in 3-D iff also non-worse on cost AND latency.
            if cb.usd_per_case <= ca.usd_per_case and cb.seconds <= ca.seconds:
                dominated = True
                break
        if not dominated:
            nondom.append({"candidate": a.candidate, "finding_class": a.finding_class})
    return nondom


# ── the deliverable ───────────────────────────────────────────────────────────

def build_map(*, stage_results: list[CascadeStageResult], cost_records: list[CostLatencyRecord],
              record: dict, headline: Interval | None = None,
              ceiling: dict | None = None) -> dict:
    """Assemble the CapabilityMap / ParetoFront deliverable (data-model). NO `best_model` field
    (SC-004/B6). `axis_label` is `representative-finding capability` while any class has
    `cases_per_class == 1` (Decision 8). The frontier `ceiling` carries no interval and is excluded
    from `pareto_nondominated` and every pair (B8/FR-020)."""
    credible_level = float(record.get("credible_level", 0.95))
    single = int(record.get("cases_per_class", 1)) == 1
    cost_by = {(c.candidate, c.finding_class): c for c in cost_records}
    pairs, underpowered = build_pairs(stage_results, credible_level)
    nondom = pareto_nondominated(stage_results, cost_by, pairs)

    by_class: dict[str, dict] = {}
    for r in stage_results:
        cl = cost_by.get((r.candidate, r.finding_class))
        # T025/FR-014: on an `unavailable` screen the cascade never got an answer, so `triggered` is
        # UNKNOWN - published as null, never as `false`. A reader (or a downstream Pareto/pair pass)
        # must not be able to mistake an infra failure for a measured "this model could not do it".
        cell = {
            "triggered": None if r.screen == "unavailable" else r.triggered,
            "smoke": r.smoke,
            "screen": r.screen,
            "single_item": r.single_item,
        }
        if r.interval is not None:
            cell["interval"] = r.interval.to_dict()
            cell["verified_k"] = r.verified_k
            cell["n"] = r.n
        if cl is not None:
            cell["usd_per_case"] = round(cl.usd_per_case, 6)
            cell["usd_per_pass"] = (None if cl.usd_per_pass is None
                                    else round(cl.usd_per_pass, 6))
            cell["seconds"] = round(cl.seconds, 3)
        by_class.setdefault(r.finding_class, {})[r.candidate] = cell

    out = {
        "axis_label": "representative-finding capability" if single else "class capability",
        "credible_level": credible_level,
        "by_class": by_class,
        "pairs": [p.to_dict() for p in pairs],
        "underpowered": underpowered,
        "pareto_nondominated": nondom,
    }
    if headline is not None:
        out["headline"] = headline.to_dict()             # kept ALONGSIDE, never merged (B7/FR-010)
    if ceiling is not None:
        out["ceiling"] = ceiling                         # frontier reference - no interval (B8)
    return out


# ── CLI (prereg / run) ────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="prover capability screen (feature 038)")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("prereg", help="append a frozen pre-registration record (before any paid call)")
    pr.add_argument("--out", required=True, help="append-only JSONL under <target>/audit/")
    pr.add_argument("--candidates", nargs="+", required=True,
                    help="id:cost_class[:ref] (ref ⇒ callable_via_harness=false)")
    pr.add_argument("--class-enum", nargs="+", required=True)
    pr.add_argument("--n-by-class", nargs="+", required=True, help="class=N ...")
    pr.add_argument("--cases-per-class", type=int, default=1)
    pr.add_argument("--credible-level", type=float, default=0.95)
    pr.add_argument("--bench", required=True, help="pinned bench id / path")
    pr.add_argument("--price-table", required=True, help="JSON file: {model: usd_per_1k_tokens}")
    pr.add_argument("--ts", default="")

    rn = sub.add_parser("run", help="run the cascade over a pre-registered battery (live wire, PAID)")
    rn.add_argument("--prereg", required=True, help="append-only prereg JSONL under <target>/audit/")
    rn.add_argument("--bench", required=True, help="pinned bench id - selects the active prereg entry")
    rn.add_argument("--tasks-from", required=True, help="battery JSON (028 shape) under <target>/audit/")
    rn.add_argument("--project", required=True, help="target Foundry project root (external)")
    rn.add_argument("--report", required=True, help="audit report file (external) - fix source")
    rn.add_argument("--out", required=True, help="capability_map JSON destination (under <target>/audit/)")
    rn.add_argument("--image", default=None, help="Foundry sandbox image (baked offline-solc)")
    rn.add_argument("--only-model", default="",
                    help="restrict to these registered model(s), comma-separated (subset run / smoke)")
    rn.add_argument("--only-class", default="", help="restrict to ONE class (cheap smoke)")
    rn.add_argument("--timeout-s", type=int, default=1800, help="per-attempt subprocess timeout")
    # agentic-loop budgets - `--attempts` does NOT bound the loop; these do (calls + wall-minutes).
    rn.add_argument("--smoke-budget-calls", type=int, default=1, help="smoke: loop calls (cheap plumbing)")
    rn.add_argument("--smoke-budget-min", type=float, default=3.0, help="smoke: loop wall-minute cap")
    rn.add_argument("--loop-budget-calls", type=int, default=8, help="screen/bayes: loop calls")
    rn.add_argument("--loop-budget-min", type=float, default=15.0, help="screen/bayes: loop wall-minute cap")

    args = p.parse_args(argv)

    if args.command == "prereg":
        candidates = []
        for spec in args.candidates:
            parts = spec.split(":")
            cid = parts[0]
            cost = parts[1] if len(parts) > 1 else "cheap"
            ref = len(parts) > 2 and parts[2] == "ref"
            candidates.append(Candidate(id=cid, cost_class=cost, callable_via_harness=not ref))
        n_by_class = {}
        for kv in args.n_by_class:
            k, v = kv.split("=")
            n_by_class[k] = int(v)
        price_table = json.loads(Path(args.price_table).expanduser().read_text(encoding="utf-8"))
        rec = make_prereg(
            candidates=candidates, class_enum=args.class_enum, n_by_class=n_by_class,
            cases_per_class=args.cases_per_class, credible_level=args.credible_level,
            pinned_bench_id=args.bench, price_table=price_table, ts=args.ts)
        dest = write_prereg(Path(args.out), rec)
        print(f"[prereg] appended entry {rec['content_hash'][:12]} → {dest}")
        return 0

    if args.command == "run":
        return _run_live(args)
    return 1


def _run_live(args) -> int:
    """T008/T011 operator wire (PAID, target present). Load the frozen prereg, assemble the battery
    from the pinned task file (028), run the cascade with the REAL attempt_fn (037 loop + byte-
    unchanged oracle), and emit the capability map + per-attempt run log under <target>/audit/."""
    from scripts.poc_queue_runner import load_pinned_tasks   # lazy: heavy import, operator step only

    project = Path(args.project).expanduser().resolve()
    report = Path(args.report).expanduser().resolve()
    tasks_from = Path(args.tasks_from).expanduser().resolve()
    out_path = _external(Path(args.out))                     # map lives under <target>/audit/

    # 1. active pre-registration entry for this bench (C1); every subject/class enforced downstream.
    record = active_record(load_prereg(Path(args.prereg)), bench_id=args.bench)

    # 2. the byte-unchanged oracle must not have drifted since prereg intent (A6/SC-005 sanity echo).
    print(f"[run] oracle verdict hash: {oracle_verdict_hash()[:12]}")

    # 3. battery ← pinned tasks (028). Each case MUST carry a fix diff or mutation_verify can't
    #    falsify - refuse loudly rather than silently score an unfalsifiable case.
    tasks = load_pinned_tasks(tasks_from, report)
    battery: list[BatteryCase] = []
    for t in tasks:
        cls = (t.get("finding_class") or t.get("class") or "").strip()
        fix = t.get("fix") or ""
        if not fix.strip():
            raise CapabilityScreenError(
                f"battery case {t.get('id')!r} has NO fix diff - mutation_verify cannot falsify it; "
                f"only fix-bearing findings belong in the prover battery (G3)")
        battery.append(BatteryCase(case_id=str(t["id"]), finding_class=cls,
                                   has_fix_diff=True))
    if args.only_class:
        battery = [b for b in battery if b.finding_class == args.only_class]
        if not battery:
            raise CapabilityScreenError(f"--only-class {args.only_class!r} matched no battery case")

    # 4. candidates ← the frozen record (order/cost_class/callable preserved).
    candidates = [Candidate(id=c["id"], cost_class=c.get("cost_class", "cheap"),
                            callable_via_harness=c.get("callable_via_harness", True))
                  for c in record.get("candidates", [])]
    if args.only_model:
        wanted = {m.strip() for m in args.only_model.split(",") if m.strip()}
        unknown = wanted - {c.id for c in candidates}
        if unknown:
            raise CapabilityScreenError(f"--only-model has unregistered candidate(s): {sorted(unknown)}")
        candidates = [c for c in candidates if c.id in wanted]

    # 5. per-attempt run log (append-only, under <target>/audit/).
    runlog_path = _external(out_path.with_name("capability_screen_runlog_038.jsonl"))
    runlog_path.parent.mkdir(parents=True, exist_ok=True)
    runlog_fh = runlog_path.open("a", encoding="utf-8")

    def runlog(entry: dict) -> None:
        runlog_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        runlog_fh.flush()
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    attempt_fn = make_live_attempt_fn(
        project=project, report=report, tasks_from=tasks_from, image=args.image,
        timeout_s=args.timeout_s, runlog=runlog,
        smoke_budget_calls=args.smoke_budget_calls, smoke_budget_min=args.smoke_budget_min,
        loop_budget_calls=args.loop_budget_calls, loop_budget_min=args.loop_budget_min)

    # 6. drive the cascade, assemble + emit the map (T011).
    try:
        stage_results, cost_records = run_cascade(
            record=record, battery=battery, candidates=candidates,
            attempt_fn=attempt_fn, log=runlog)
    finally:
        runlog_fh.close()
    cmap = build_map(stage_results=stage_results, cost_records=cost_records, record=record)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cmap, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[run] capability map → {out_path}")
    print(f"[run] axis={cmap['axis_label']} underpowered={cmap['underpowered']} "
          f"pareto={len(cmap['pareto_nondominated'])} cells")
    return 0


if __name__ == "__main__":
    sys.exit(main())

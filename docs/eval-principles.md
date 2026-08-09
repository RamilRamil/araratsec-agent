---
type: Reference
title: Eval / verification principles for generated artifacts
description: Positive-signal verdicts, second-signal corroboration, and operator SOPs against false positives.
tags: [eval, verification, false-positives, mutation-verify, operator-sop]
lang: en
status: stable
generated:
  by: human:ramilmustafin
  at: 2026-08-07T14:06:34+04:00
sources:
  - resource: scripts/poc_queue_runner.py
    title: PoC-workability harness (_compiled / mutation_verify)
---

# Eval / verification principles for generated artifacts

How this project verifies whether an automated check over an LLM-or-tool-generated
artifact (a compiled PoC, a passing test, an extracted finding) is actually telling the
truth. Written after a real incident (spec
[006-eval-verification-robustness](../specs/006-eval-verification-robustness/)) where a
verdict was wrong with full confidence, and nothing about running it raised a flag.

This is a general engineering practice for tooling, distinct from and lighter-weight
than the kernel's security invariants (Principle I, `tests/security/`) — see
[the secure-agent-kernel repo](https://github.com/RamilRamil/secure-agent-kernel) for those. This document applies wherever this project (kernel,
any capability pack, or standalone tooling like the PoC-workability harness) writes an
automated check that produces a success/failure verdict.

## The principle

**Every automated verdict over a generated artifact must be based on a positive
signal — a marker that can only appear on genuine success — never on the absence of a
list of anticipated failure signals (a denylist).**

A denylist's failure mode is invisible by construction: it doesn't raise, doesn't log
an anomaly, it just returns the wrong answer with full confidence. On 2026-07-05, the
PoC-workability harness's compile check was:

```python
return "Compiler run failed" not in blob and "Compilation failed" not in blob
```

A genuine compile failure worded differently (`Error: Encountered invalid solc version
...`) used neither phrase, so this returned `True` for 3 genuinely-failed compiles —
producing a false "all findings compiled" milestone recorded in `docs/roadmap.md`.
Fixed to a positive signal:

```python
_RAN_TEST_RE = re.compile(r"Ran \d+ tests?")
return bool(_RAN_TEST_RE.search(stdout + "\n" + stderr))
```

`forge` prints `Ran N test(s) for ...` if and only if it got past compilation and
actually executed the suite — regardless of whether the test then passed, failed, or
reverted.

**Before an automated verdict is recorded as a milestone/success claim in project
documentation, it must be corroborated by a second, independently-computed signal** —
not a second read of the same transcript with a similar method. A cross-check whose
second signal shares its data source and method with the first shares its blind spot
too. This requirement applies to *documented claims*, not every internal per-attempt
log line (that would make tooling prohibitively slow for no safety benefit).

## Audit checklist (reusable format)

Run any set of automated verdict-producing checks through this table before trusting
their verdicts. Full format + this feature's filled example:
[specs/006-eval-verification-robustness/contracts/audit-checklist.md](../specs/006-eval-verification-robustness/contracts/audit-checklist.md).

| Check | Signal type | Blocking? | Notes |
|---|---|---|---|
| `_compiled()` | positive (`Ran \d+ tests?`) | yes | corrected 2026-07-05 (was a denylist) |
| `_poc_defects()` | positive (requires active assert/import present) | yes | its one narrow exception (own-declaration re-mock check) is against the artifact's own controlled vocabulary, not an open-ended tool message |
| `mechanism_signal()` | positive, but diagnostic | **no** | cannot tell WHICH contract instance a shared-interface method was called on — logged every attempt, never gates an outcome |

When you add a new automated check anywhere in this project: ask "what marker can ONLY
appear on genuine success" (not "what failure messages have I seen"); write a
known-good AND a known-bad test worded differently than you'd naturally guess; decide
out loud whether it blocks an outcome or is diagnostic-only; add a row to the audit
table in the same change.

## Mechanism-verification recommendation: SmartGraphical

**Question**: can SmartGraphical's call-graph analysis
(`sr_agent/packs/audit/tools/smartgraphical.py`) replace `mechanism_signal()`'s
regex-based check with a real, type-aware "was THIS function on THIS contract type
actually called" check?

**Verdict: ADAPT — not adopt now, not defer outright.** SmartGraphical's
`cross_type_call` graph edges are structurally the right mechanism (they resolve a
call across a declared variable's type — exactly what a regex cannot do), but it has
never been driven over a Foundry test file (only over audited target contracts), and
the external install isn't present in this environment. Full reasoning, what it would
close, and the conditions that would change this verdict:
[specs/006-eval-verification-robustness/contracts/mechanism-check-recommendation.md](../specs/006-eval-verification-robustness/contracts/mechanism-check-recommendation.md).

**Follow-up**: the same class of problem (the model inventing plausible-but-wrong
identifiers because the real definition isn't visible to it) recurred at the *drafting*
stage, not just the *verification* stage — a struct's real fields aren't shown anywhere
the model can see them, so it invents field names. See
[specs/007-ast-grounded-poc-drafting](../specs/007-ast-grounded-poc-drafting/) for the
AST-parser-backed, agentic fix to that class of problem (a different, earlier point in
the pipeline than SmartGraphical's post-hoc call-graph check, and — per the research
above on De-Hallucinator — a well-studied problem shape: use the model's own
draft/error as the query to retrieve precise, real definitions).

## Operator SOP: reconstruction refusal is an operator handoff, not a model-feedback loop

The post-PASS falsifier (`mutation_verify`, feature 010) proves a finding by applying
its fix to a temp copy and re-running the PoC: the PoC must FAIL on the patched target
(`verified`) — a PoC that still passes on the fix (`unverified_pass`) proved nothing.
But `mutation_verify` can only run if it has an applyable patch. An audit report's
```diff``` block is **illustrative** — correct file headers, but hunk markers are prose
with no line numbers — so it is reconstructed into a real patch (feature 025,
`patch_reconstruct.py`). Reconstruction **refuses** (`ReconstructionRefused`) rather
than guess: `context_mismatch` means the report's fix-diff context lines don't match the
target source verbatim, so there is no safe place to land the hunk. A refusal makes
`mutation_verify` `unavailable` — the finding never reaches the falsifier.

**The SOP** (Principle II — the oracle is never relaxed, only fed correctly):

> When reconstruction refuses (`context_mismatch`), the **operator** reconstructs the
> fix by hand from the report's illustrative diff and supplies it as an operator
> `fix_patch`, out-of-band. The operator `fix_patch` has precedence (feature 025
> FR-005): it is applied AS-IS, bypassing reconstruction entirely, so `mutation_verify`
> can run. This is a human handoff, not an automated recovery.

**Why the refusal signal does NOT go back to the model.** `context_mismatch` is a
*harness-side* fact — the report's diff doesn't anchor to source — that the model cannot
move by re-drafting its PoC. Routing it into the model's fix loop as "feedback" targets a
signal the model has no lever on; it was proposed (spec 044 PART 2) and retired. The
refusal is actionable only for the operator, who can read the real source and produce a
landing patch. (Confirmed on a live case 2026-07-30: a finding that dead-ended on
`reconstruction_refused` in the automated loop reached `verified` as soon as an operator
`fix_patch` was supplied — the pass was load-bearing on the real bug all along.)

**Do not build a feature for this until it is measured.** On the one case observed so far
(≈1 of 3 fix-bearing findings in a discriminator run), the operator handoff is cheap and
sufficient. Automating it (better fix-diff anchoring, a first-class operator-`fix_patch`
cascade stage) is only worth speccing if `reconstruction_refused` proves **recurrent
across many findings** — and that must be established by a pre-registered measurement
(the 038 capability-screen pattern: fixed candidate set + thresholds fixed before the
run), not by generalizing from one artifact. Until that signal exists, the SOP above is
the whole answer.

## Operator SOP: defend diagnoses (not just PoCs) against false positives

The oracle (`mutation_verify`) defends claims about the **agent's output** — "this PoC is
real" is machine-checked (`vacuous_pass` / `unverified_pass` / `mutation_unverified` mark
the false positives). But claims about **our own diagnosis** — "finding X died because of
compile-mode Y", "fix Z improved the funnel" — have **no oracle**. They are operator
narrative, and narrative is where false-positive *hypotheses* breed. There is, by nature,
no run-status for a diagnosis-level FP: the claim is *about* runs, not an outcome *of* one.

**The incident.** A memory note asserted "H-05 is a new third compile-failure mode." The
artifact refuted it: the story was stitched from **three different `run_id`s** (one
timed out, one `passed_verified`, one `lookup_failed`). It was a lead recorded as a fact —
a textbook false positive. (This mirrors the field literature: HARKing, the garden of
forking paths, the 750 GeV diphoton bump that ~500 papers "explained" before it vanished.)

**The SOP — a claim is a *lead*, not a *diagnosis*, until it passes, in order:**

> 1. **Mechanize it.** Can a machine check this claim (grep an event, count occurrences)?
>    If yes, run the check — that ends the argument with a fact. ("047 helped" → fixer
>    fire-count; it was `0`, which refuted the attribution outright.)
> 2. **Pin one run.** Every claim cites `run_id + finding_id + verbatim event line`.
>    **Never fuse events across `run_id`s** — that is exactly what produced the H-05 FP.
> 3. **Name the falsifier first.** State what observation would prove the claim wrong
>    *before* believing it. No nameable falsifier ⇒ it stays a lead.
> 4. **Show a control.** A run/finding where the effect did **not** occur.
> 5. **Rule out competitors (ACH).** List the ≥2 rival explanations and the discriminating
>    evidence, not just confirmation of the favored one.

Post-hoc exploration is fine — but it must be **labeled exploratory and re-confirmed**,
never re-cited as an a-priori fact. A recalled memory that names an artifact is a pointer
to **re-verify**, not a fact to quote.

**The one mechanizable slice (the rest is discipline, not code).** The real methodological
sin behind the H-05 run was a **confounded arm**: the harness ran as
`code_version = "cc7169f-dirty" = 047 + cc7169f` — two treatments in one arm, so neither
can be attributed. Gate 1 applied to ourselves: a harness/orchestration guard that
**stamps run provenance and refuses silent bundling** — flag or hard-fail when
`code_version` carries `-dirty` (uncommitted changes) or bundles more than one landed
change under test — so an arm cannot confound two treatments unremarked. This is the *only*
part of this SOP worth a spec, and only a tiny FR (provenance stamp + confound guard); it
is **not** a priority over the prover (verified) axis. Everything else here is operator
discipline with nothing to build.

**Do not spec the checklist itself.** It changes how the operator reasons, not harness
code (the H-02 precedent: an SOP, not a feature). n = 1 incident; speccing epistemic
hygiene while the verified axis is unmoved is displacement. The payoff is bounded — it
prevents one bogus spec (the "Mode C" that this SOP just stopped) — so cap the investment
accordingly.

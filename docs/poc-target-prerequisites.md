# PoC target prerequisites (operator SOP)

What must already exist on the **analyzed Foundry project** (`POC_PROJECT`) before
`scripts/poc_queue_runner.py` can usefully draft and (optionally) fork-verify PoCs.

This is **target-side** setup. Agent quickstart (`.env`, Ollama, Langfuse) does not cover it.
Nothing target-specific is committed into this repo.

Flow context: [diagrams/poc-writing-flow.md](diagrams/poc-writing-flow.md).

---

## Mental model

```
Target already has a tracked Deploy/Setup base
  → runner inherits it; may synth an extension if a needed type is missing
Target has no usable deploy harness
  → operator writes/points a scaffold; otherwise expect base-insufficient
```

The runner is built to **inherit the project's real deploy infrastructure**, not to
bootstrap a full protocol stack from an empty `test/` tree.

---

## What the runner expects on the target

### 1. Foundry project root

- `foundry.toml` (note `test = ...` if non-default)
- Dependencies resolvable offline in the sandbox (`lib/`, `node_modules/`, remappings)
- Solidity sources for in-scope contracts

### 2. A deploy / PoC scaffold (required)

A **tracked** (git original) test base the model will inherit — typically named like
`*Base`, `*Setup`, `*Deploy`, `*Harness`, or `*Fixture`.

| Source | How |
|--------|-----|
| Auto-discovery | Most-inherited matching base under the Foundry `test` dir (git-tracked only) |
| Operator override | `--test-scaffold path[,path...]` or env `POC_SCAFFOLD` |
| Disabled | `--no-scaffold` (only for deliberate ablations; expect weak results) |

A sufficient base usually wires: access control / roles, CDO (or vault stack), accounting,
strategy + cooldowns the suite needs, and helpers to seed deposits.

**Anti-pattern:** do not commit skill-generated or answer PoCs as the scaffold. Auto-discovery
ignores untracked files so the model is not handed a solution; tracked “answer” bases defeat
the experiment.

### 3. Finding-specific coverage of the scaffold

If the finding’s target contract type is **not** declared/deployed on the resolved base
(e.g. base deploys the CDO stack but not `SharesCooldown`), `scaffold_missing_types` **gates**
the finding — drafting on a known-insufficient base is **disallowed** (not a soft diagnostic).
The harness then:

1. Tries to **synthesize an extension** base that `is ExistingBase` and deploys the missing
   type(s) (feature 011); if that base compiles, drafting proceeds on it.
2. Otherwise routes to a terminal — and the two terminals are **accounted differently**:

| Terminal | Nature | Counts toward the model’s rate? | When |
|----------|--------|--------------------------------|------|
| `base-insufficient` | `harness-infra` | **No — excluded** (environment gap) | the lookup route could not run (no symbol index / lookup budget 0), **or** no deploy base could be resolved at all (spec 001) |
| `lookup_failed` | `model` | **Yes — retained** in the denominator | the lookup route **ran** (index consulted per missing type) and no usable deployment was found — a genuine model miss, never re-labelled as infra |

Do **not** treat these as interchangeable: `base-insufficient` is environment and leaves the
model’s denominator; `lookup_failed` is a model-column miss and stays in it. Conflating them
inflates the measured capability rate.

**Absent base (spec 001).** When *no* deploy base can be resolved for a finding and scaffolding
was **not** deliberately disabled (`--no-scaffold`), the runner short-circuits to
`base-insufficient` (environment) *before* the missing-type gate — it does **not** silently draft
on a “no base provided” prompt and charge the failure to the model. The agent does **not** invent
a full protocol harness when no existing base is present.

### 4. Fork / RPC (for green `forge test`, not for path A)

Many contest PoCs call `vm.createFork` / `vm.envString("MAINNET_RPC_URL")` and need an
**archive** mainnet RPC at a pinned block.

| Outcome | Meaning |
|---------|---------|
| `compiled` (path A) | Builds + structurally real under sandbox `--network none` / offline — default success bar |
| `passed` | Green `forge test` (needs fork + RPC when the PoC is fork-based; `--require-pass` / `--fork`) |

Without `MAINNET_RPC_URL` (or equivalent passed into the runner’s fork path), fork PoCs
fail at `setUp`. That is infra, not a bad finding extraction.

Bounty / seeding rules (e.g. tranches seeded ≥ N assets) live on the **target** program
docs; PoCs must respect them if the report/program requires it.

---

## Operator checklist (before `poc_queue_runner`)

1. [ ] `POC_PROJECT` points at the Foundry root; `POC_REPORT` at the audit report.
2. [ ] Target builds locally (`forge build` / known CI image).
3. [ ] A tracked deploy base exists **or** `--test-scaffold` / `POC_SCAFFOLD` is set. If you set
      it, the path must resolve to a file — a typo pre-flight-aborts the whole run (spec 001 FR-011),
      it is **not** silently ignored.
4. [ ] That base (or a known synth path) can reach contracts the findings need; if not,
      extend the base on the target or accept synth / `base-insufficient`.
5. [ ] For fork PASS: archive `MAINNET_RPC_URL` available to the runner/sandbox fork path;
      pinned blocks in tests exist on that RPC.
6. [ ] Host memory enough for `via_ir` cold builds if the target uses them (OOM ≠ model miss).
7. [ ] Do not seed grounding with finished exploit PoCs for the same findings.

---

## What the agent can and cannot do

| Can | Cannot |
|-----|--------|
| Auto-find or use operator scaffold | Bootstrap a full stack with no deploy base |
| Gate on missing types (disallow drafting on an insufficient base) | Guarantee the right strategy variant (e.g. Neutrl vs Midas) without the right base |
| Synth an incremental extension base | Turn path-A `compiled` into fork `passed` without RPC/network |
| Label an absent/insufficient base as environment (`base-insufficient`, harness-infra) | Silently accept a typo’d `--test-scaffold` (it pre-flight-aborts) or charge an absent base to the model |
| Keep a genuine model miss (`lookup_failed`) in the model’s denominator | Replace operator bounty/seed judgment |

---

## Ask vs generate — what the runner does with a missing input

The runner is a **non-interactive batch process**. It never pauses mid-run to request a specific
missing file: prerequisites are satisfied **up front** (this SOP), and whole-run blockers surface
as **pre-flight aborts**, not per-finding prompts.

| Missing input | What happens |
|---------------|--------------|
| Operator scaffold set but unresolved (typo) | **Pre-flight abort** (`exit 2`, names the path) — spec 001 FR-011 |
| Fork RPC (`--fork` without `MAINNET_RPC_URL`) | **Pre-flight abort** |
| Model host down (Ollama not up) | **Pre-flight abort** (warm-up fails) |
| No deploy base at all (not `--no-scaffold`) | Per-finding **`base-insufficient`** (environment; excluded from the model rate) |
| A needed contract **type** missing on an existing base | **Generate**: synth an extension base (feature 011); else `base-insufficient` / `lookup_failed` per §3 |
| Deliberate `--no-scaffold` ablation | Drafts on “no base provided”; outcomes **stay in the model column** (raw-capability measurement) |

Two honesty boundaries follow from this:

- **“Ask” is up-front, not interactive.** There is no runtime channel for the agent to request a
  file; if a prerequisite is unmet, the operator fixes it and re-runs.
- **“Generate” fills a partial gap only.** Synthesis extends an *existing* base to add a missing
  type — it never fabricates a base where none is resolvable. An absent base is an environment
  gap, not something the model is expected to invent.

---

## Related

- [diagrams/poc-writing-flow.md](diagrams/poc-writing-flow.md) — draft → compile → fix loop
- [audit-agent.md](audit-agent.md) — pack surfaces including the PoC runner
- [eval-principles.md](eval-principles.md) — mutation-verify / operator fix_patch handoffs
- `scripts/poc_queue_runner.py` — `resolve_scaffold`, `scaffold_missing_types`, `synthesize_scaffold`
- `scripts/scaffold_causes.py` — cause → nature map (`harness-infra` vs `model`)

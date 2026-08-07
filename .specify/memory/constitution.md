<!--
Sync Impact Report
- Version change: 1.0.0 → 2.0.0 (2026-07-23)
- Rationale: MAJOR — Principle V is REDEFINED (backward-incompatible). The local-model
  requirement is dropped: it failed in practice (spec 022 — the local model provably could not
  produce a working PoC; every measured proof result in 029/031/032 comes from hosted models).
  Replaced by kernel provider-agnosticism + a smallest-capable-model rule, preserving the original
  intent (no vendor hostage, no cost hostage) without asserting a rule the project cannot keep.
- SUPERSEDED by this amendment: spec 022's Acceptance Scenario 2 ("the operator selects the local
  model (default)") — the harness default provider is now a hosted one. Spec 022 stays as the
  historical record; this constitution governs.
- Prior ratification (1.0.0):
- Rationale: initial ratification; fills the empty template with concrete principles.
- Principles defined:
  I. Secure-Kernel Trust Invariants (NON-NEGOTIABLE)
  II. Human Authority for Privileged & Irreversible Actions
  III. Kernel / Capability-Pack Separation
  IV. Human-Gated Knowledge Promotion
  V. Provider-Agnostic Kernel, Smallest Capable Model (amended 2.0.0)
- Added sections: Security Requirements; Development Workflow & Quality Gates.
- Removed sections: none (template placeholders replaced).
- Templates reviewed:
  ✅ .specify/templates/plan-template.md — generic "Constitution Check" gate; no change needed (it reads this file).
  ✅ .specify/templates/spec-template.md — no mandated sections conflict.
  ✅ .specify/templates/tasks-template.md — test-first + security task types compatible.
- Follow-up TODOs: none. Source of truth for content: docs/roadmap.md "Decisions locked".
-->

# SR-agent Constitution

SR-agent has a dual goal, in priority order: (1) build a **memory-injection-resistant secure agent** — the reusable, task-agnostic core; (2) demonstrate it via an **audit agent** — the first capability pack. This constitution governs goal (1). Task-specific behavior (goal 2) rides on top and MUST NOT dilute it.

## Core Principles

### I. Secure-Kernel Trust Invariants (NON-NEGOTIABLE)

The deterministic orchestration plane is the trust boundary; model output never drives control flow directly. These invariants hold on EVERY turn, not just at entry:

- Every tool result and every prior-turn artifact re-entering context is untrusted DATA, wrapped in `[DATA START]..[DATA END]`, sanitized, and NEVER executed or obeyed as an instruction regardless of its phrasing.
- The `SourceType` trust hierarchy is authoritative: `human_input` > `tool_output` > `external_llm_output` > `llm_inference`.
- Model and relay output is `external_llm_output` and MUST NEVER be promoted to `human_input`, no matter how many turns it survives.
- Memory is HMAC-signed, append-only; records failing verification are silently dropped (no tamper oracle).
- A per-turn tool-call budget bounds loops; on reaching it the agent stops calling tools and reports state honestly.

Rationale: the entire project exists to resist memory/prompt injection. Every one of these is a testable line the MI harness exercises; weakening any of them is a defeat of the project's purpose, not a trade-off.

### II. Human Authority for Privileged & Irreversible Actions

Irreversible or privileged-status-changing actions route through the out-of-band confirmation channel and MUST NOT execute from within a model turn. This covers the `REQUIRES_HUMAN_CONFIRMATION` status set (`verified_safe`, `skip_analysis`, `audit_complete`) and every `write_execute`-class tool. Findings are hypotheses, confirmed only by a passing PoC — never by model assertion. A convenience surface (e.g. chat mode) MUST NOT create a shortcut around this gate.

Rationale: the one thing that carries real-world authority is an explicit human act on a separate channel; anything the model "decides" is a proposal, not a decision.

### III. Kernel / Capability-Pack Separation

The secure kernel is task-agnostic. Task-specific capability — audit tools, concrete action types, planner stages, finding models, domain privileged-statuses — lives in a capability pack. A pack is DECLARATIVE and CONSTRAINED: it MAY register tools and mark actions high-risk, but MUST NOT weaken any kernel guarantee (Principles I, II, IV). That a pack cannot lower a guardrail is itself a security property and MUST be tested. YAGNI: document the boundary and interface; do NOT build a dynamic plugin registry until a second pack actually exists.

Rationale: we learn to build a secure core, demonstrated on audit. Entangling task logic into the kernel makes the security story unportable and the core untestable in isolation.

### IV. Human-Gated Knowledge Promotion

Knowledge that steers pipeline construction is embedded ONLY by explicit human command. Observations derived from tool output (errors, gotchas, latencies) NEVER self-promote into steering knowledge. A model's draft lesson is `llm_inference`; only a human's review-and-command elevates it to `human_input` and into the applied knowledge base.

Rationale: an auto-loop that turns error text (which contains attacker-influenced tool output) into pipeline-steering knowledge is a memory-injection channel you build yourself ("retrospective poisoning"). Human-gating collapses that risk to zero.

### V. Provider-Agnostic Kernel, Smallest Capable Model

The kernel's security properties MUST NOT depend on which model or provider drives it. No trust invariant (I), confirmation gate (II), or knowledge gate (IV) may be relaxed — or assumed stronger — because of the provider in use. Provider choice is a capability and cost decision, NEVER a security one.

Model selection follows the **smallest-capable-model rule**: use the least capable (smallest, cheapest) model that demonstrably clears the task's bar, and justify any step up with a MEASURED failure of the smaller one, recorded in the run artifact — not with an assumption that bigger is better.

A capability pack MAY require a hosted model to be USEFUL: the audit pack's proof harness is hosted-model-dependent, because the local model provably could not produce a working PoC (spec 022). The kernel itself MUST stay runnable against any provider — including a local model or the manual relay — should one become adequate again. Relay output remains `external_llm_output` and is never promoted (relay ≠ authoring).

Rationale (amended 2026-07-23): the original principle REQUIRED the core loop to run on a local model. That did not survive contact with the task — the local model could not produce a working PoC (spec 022), and every measured proof result since (029, 031, 032) comes from hosted models. Asserting a requirement the project routinely violates erodes the authority of the constitution as a whole, including the invariants that actually matter (I, II, IV). The durable part of the original intent is preserved twice over: "security must not be hostage to a vendor" becomes kernel provider-agnosticism, and "must not be hostage to cost" becomes the smallest-capable-model rule.

## Security Requirements

- **MI-resistance is the top quality bar.** The Memory-Injection harness (`tests/security/`) is the primary gate: target Attack Success Rate = 0 for protected runs. A change that raises ASR above 0 does not ship.
- Untrusted-data handling (Principle I) and the confirmation gate (Principle II) each have dedicated tests; new tools/actions in any pack add their own MI + confirmation coverage.
- Sandboxed execution: tools that run attacker-influenced code (static analyzers, `forge test`, PoCs) execute only inside the network-isolated, capability-dropped, ephemeral Docker sandbox.

## Development Workflow & Quality Gates

- Spec-kit flow for non-trivial features: `specify → plan → tasks → analyze → implement`. `/speckit-analyze` treats this constitution as non-negotiable authority; constitution conflicts are CRITICAL.
- Test-first for security-critical behavior: the guarantee is written as a failing test before the implementation that satisfies it.
- Reuse-first: before adding code, confirm the kernel primitive does not already exist (much of the kernel is built; the recurring bug is wiring, not absence).
- Commits happen only on explicit request; commit messages end with the required Co-Authored-By trailer.

## Governance

This constitution supersedes ad-hoc practice for the core loop. Amendments require: a written rationale, a version bump per the policy below, and propagation to dependent templates/specs in the same change.

Versioning policy (semantic): MAJOR = backward-incompatible principle removal/redefinition; MINOR = new principle or materially expanded section; PATCH = clarification/wording. Compliance is reviewed at `/speckit-analyze` and before merge of any feature touching the kernel or a pack boundary. Complexity that appears to violate a principle must be justified in the feature's Complexity Tracking or rejected.

**Version**: 2.0.0 | **Ratified**: 2026-07-02 | **Last Amended**: 2026-07-23

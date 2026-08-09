<!--
Sync Impact Report
- Version change: 2.0.0 → 2.1.0 (2026-08-09)
- Rationale: MINOR — Principle II is NARROWED and RELOCATED (not merely clarified). The
  privileged-status set (`verified_safe`, `skip_analysis`, `audit_complete`) is no longer hardcoded
  in the kernel; it is DECLARED by the active capability pack and BOUND by the kernel at session
  construction, immutable for the session. The kernel enforces the gate over exactly what the active
  pack declares. This changes the SHAPE of the guarantee (kernel-absolute → pack-declared-bound-at-
  session-start) while preserving its intent, so it is a MINOR bump, not a PATCH clarification.
- Security rationale: the narrowing is made deliberate and tested by hostile-pack test H4 — an
  empty/reduced `privileged_statuses` means "this pack has no privileged statuses," NOT "gate
  disabled," and under-declaration cannot bypass a kernel-enforced status (post-change there is no
  kernel-default status to bypass; the concept is entirely pack-scoped). The confirmation gate for
  `write_execute`-class actions is UNCHANGED — still kernel-derived from `action_class`.
- Principle III: no textual change to the principle's mandate (it already assigns domain metadata to
  the pack); this amendment records the kernel-generic EXCEPTION so a future reader does not misread
  the retained ids as a violation. The exception carries TWO WEIGHTS: the control/memory machinery
  (`write_memory`, `request_human_confirmation`) and loop signals (`escalate`, `complete`) are
  kernel-owned by STRUCTURAL NECESSITY (the kernel's own loop constructs/branches on them — Principles
  I/II — so they cannot live in a pack even in principle); the scope-bounded reads (`read_file`,
  `search_code`) are kernel-owned by ANTI-DUPLICATION CONVENIENCE over a kernel-owned safety primitive
  (the path-containment guard `_contained`/`_check_filepath` must be kernel-side; the read ids could
  technically live in a pack importing it, but are kept generic so every pack inherits reading free).
- Cross-repo: authored here (constitution source of truth) as a standalone governance change landing
  BEFORE secure-agent-kernel feature-001 PR-1; the kernel's `.specify/memory/constitution.md` copy
  mirrors this verbatim (kernel does not author it).
- Templates reviewed: ✅ plan/spec/tasks templates read this file; no template change required.
- Follow-up TODOs: none.
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

Irreversible or privileged-status-changing actions route through the out-of-band confirmation channel and MUST NOT execute from within a model turn. This covers every `write_execute`-class tool and the pack-declared privileged-status set. That status set is NOT hardcoded in the kernel: each capability pack declares its own privileged statuses (the audit pack declares `verified_safe`, `skip_analysis`, `audit_complete`), and the kernel BINDS that set into episodic memory at session construction — immutable for the session, enforced against untrusted source tiers. An empty or reduced set means "this pack has no privileged statuses," NOT "the gate is disabled." Findings are hypotheses, confirmed only by a passing PoC — never by model assertion. A convenience surface (e.g. chat mode) MUST NOT create a shortcut around this gate.

Rationale: the one thing that carries real-world authority is an explicit human act on a separate channel; anything the model "decides" is a proposal, not a decision.

### III. Kernel / Capability-Pack Separation

The secure kernel is task-agnostic. Task-specific capability — audit tools, concrete action types, planner stages, finding models, domain privileged-statuses — lives in a capability pack. A pack is DECLARATIVE and CONSTRAINED: it MAY register tools and mark actions high-risk, but MUST NOT weaken any kernel guarantee (Principles I, II, IV). That a pack cannot lower a guardrail is itself a security property and MUST be tested. YAGNI: document the boundary and interface; do NOT build a dynamic plugin registry until a second pack actually exists.

Kernel-generic EXCEPTION: the kernel still owns a small set of NON-domain, task-agnostic action ids it provides to every pack — the control/memory machinery (`write_memory`, `request_human_confirmation`) and the scope-bounded reads (`read_file`, `search_code`). These stay in the kernel for two distinct reasons: the machinery ids are a structural necessity (the confirmation and memory mechanisms are kernel guarantees), and the read ids are anti-duplication over the kernel's own path-containment primitive (Principle I) — every pack would otherwise re-roll the same traversal guard. This exception is NOT a licence to keep domain vocabulary in the kernel: an id belongs to the kernel only if it is genuinely task-agnostic and carries no audit meaning.

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

**Version**: 2.1.0 | **Ratified**: 2026-07-02 | **Last Amended**: 2026-08-09

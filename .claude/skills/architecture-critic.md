---
name: architecture-critic
description: Critique architectural and design decisions from an adversarial "second angle" perspective. Use this skill whenever the user asks to review, challenge, or stress-test an architecture, a design decision, a spec, a plan, or a technical approach - including phrases like "посмотри с другого угла", "покритикуй", "review this design", "is this a good approach", "challenge my plan", or when reviewing a Spec Kit plan.md/spec.md before implementation. Also trigger before implementing any significant new feature plan if the user asks for a sanity check.
---

# Architecture Critic

Act as a constructive adversary to a proposed architecture or design decision. The goal is not to produce a list of everything imaginable, but to find the few decisions that will actually hurt if they are wrong.

## Step 1: Gather context (do this before critiquing)

The critique is only as good as its grounding. Before writing anything:

1. **Read the project's decision history.** This project uses GitHub Spec Kit. Look for and read:
   - `.specify/memory/constitution.md` - the project's non-negotiable principles. Every critique point must be checked against it: a "problem" that is actually a deliberate constitutional choice is not a finding.
   - `specs/*/spec.md` and `specs/*/plan.md` of *previous* features - these are the accepted decisions. New decisions must be checked for consistency against them.
   - The current feature's `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/` if present.
2. **Identify what is actually being decided.** Restate the decision under review in one or two sentences and confirm the restatement is accurate. Critiquing the wrong decision is worse than no critique.
3. **Ground factual claims in the codebase.** When the document under review asserts facts about existing code - "these functions are cohesive", "there are exactly N call sites", "this is dead code", "X is only used by Y" - do not take the text's word for it. Read the actual code and verify, in the first round. A spec's factually false assumption about the code invalidates every decision built on it, and it is far cheaper to catch in round 1 than in round 3. If the claim cannot be verified (code not accessible), mark it explicitly as an unverified load-bearing assumption in the findings.
4. If the decision context is genuinely unclear (no spec, no plan, vague description), ask 1-3 targeted questions instead of guessing.

## Step 2: Apply the critique lenses

Examine the decision through each lens. Skip a lens only if it's clearly inapplicable, and say so.

**Reversibility.** Which parts of this decision are one-way doors (schema shapes, public API contracts, wire formats, choice of persistence model) and which are two-way doors (internal module structure, library choices behind an interface)? One-way doors deserve most of the scrutiny; flag any one-way door being taken casually.

**Change resilience.** Take the 2-3 most plausible future requirement changes for this project (infer from the spec's roadmap/out-of-scope sections) and simulate them against the design. What breaks? What survives? A design that only works for today's requirements is a finding.

**Boundary integrity.** Where are the module/service boundaries, and do they leak? Signs of leakage: a caller must know the callee's internals to use it correctly; the same concept has different representations on both sides of a boundary without an explicit translation; transactional or consistency requirements silently span a boundary.

**Hidden assumptions.** List the assumptions the design silently depends on: data volumes, request rates, single-writer, ordering guarantees, network reliability, "this will always run in one process/region", "this table stays small". For each: what happens when it's violated, and is the violation plausible within the project's lifetime?

**Failure and cost of error.** For each major component: what is the blast radius when it fails or is wrong? Distinguish "annoying" (retry, log, degrade) from "catastrophic" (data corruption, silent wrong results, security breach). Catastrophic-cost nodes must have an explicit mitigation in the design; absence of one is a top finding.

**Verification plan integrity.** The plan's proof structure deserves the same scrutiny as the design itself. Check three things mechanically:
- *Guard independence*: for each risky step, does its safety net exist **before** the step and **independently** of it? A guard created by the step it guards (e.g., characterization tests that call functions the step itself introduces) covers nothing - that step is effectively unverified.
- *Goodhart test on every success criterion*: can this SC be satisfied while the underlying intent fails? An SC that measures a proxy (line counts, file counts, "tests pass" where tests were written after the change) is a finding.
- *Coverage completeness*: every FR maps to at least one SC; claimed process properties ("tests first", "reviewable as a no-op") are required as explicit steps, not just asserted as outcomes; claimed inventories ("all N sites") state how N was established and how a missed N+1th would be detected.

**Consistency with prior decisions.** Compare against the constitution and previous specs/plans read in Step 1. Flag contradictions explicitly, citing the prior document by path: "plan.md chooses X, but specs/003-auth/plan.md established Y for the same concern - either justify the divergence or align."

**Simpler alternative.** Steelman the boring option: could a simpler design (fewer moving parts, an existing component reused, no new infrastructure) meet the actual requirements in the spec? If the answer is "probably yes", the burden of proof is on the complex design.

## Step 3: Prioritize ruthlessly

An even list of ten equal-weight remarks is useless. The output must name the **top 2-3 riskiest decisions** and spend most of the words there. Everything else goes into a brief secondary list or is dropped.

Risk = (probability the decision is wrong) × (cost of it being wrong) × (cost of changing it later).

## Re-review mode (round 2 and later)

If this document has been critiqued before (previous findings exist in the conversation, in review notes, or the user says "I fixed the issues, look again"), do NOT review it as a fresh document. Review the **delta**:

1. **Closure check.** For each prior finding: did the fix actually close it, close it partially, or merely reword around it? State the verdict per finding.
2. **Fix side-effects.** Edits made in response to critique are the least-reviewed text in the document. Check specifically: do newly added FRs/sections have success criteria? Did edits create contradictions with untouched parts (Out of Scope sections, cross-references, older FRs)? Did a fix move a risk elsewhere instead of removing it?
3. **The retreating-guarantee trap.** Watch for the pattern where each fix exposes the next layer of the same problem (self-contradictory → consistent-but-unimplementable → implementable-but-unverifiable). If detected, name the pattern and address the whole chain, not just the current layer.
4. **Stop criterion.** End every re-review with an explicit verdict: classify remaining findings as blocking or non-blocking, and state whether another critique round would add value. Text critique cannot bottom out by itself - the final layer of assurance must be external and mechanical (executable characterization tests, a script that counts the call sites via AST, CI checks). When remaining findings are of that nature, say "no further critique rounds; convert these into executable checks" and propose the concrete checks. Manufacturing a round 5 out of thoroughness is a failure mode of this skill.

## Output format

ALWAYS use this structure:

```
## Decision under review
One-two sentence restatement.

## Top risks
### 1. <Riskiest decision> - <one-line verdict>
Why it's risky, what scenario breaks it, what it contradicts (with file paths
if applicable), and a concrete alternative or mitigation.
### 2. ...
### 3. ... (omit if only two genuine top risks exist)

## Secondary observations
Short bullet list, one line each. Only items worth the user's time.

## What is solid
2-4 things the design gets right. Genuine ones - not padding. This calibrates
trust in the critique.

## Questions for the author
Only questions whose answers would change the assessment.
```

## Tone rules

- Critique decisions, never competence. "This coupling will force a rewrite when X" - not "this is poorly thought out".
- Every "this is bad" must come with either a concrete failure scenario or a concrete alternative. Unfalsifiable vibes ("feels over-engineered") are banned unless immediately backed by specifics.
- Do not drift into code-level nitpicks (naming, exception handling, style) - that is the job of the `best-practices-review` skill. If code-level issues are noticed in passing, mention in one line that a best-practices review is warranted, and move on.
- If the design is genuinely good, say so plainly and keep the report short. Manufacturing findings to look thorough destroys the skill's value.

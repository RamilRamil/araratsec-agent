# Needle in the Haystack: LLMs for Vulnerability Finding

**Source**: https://devansh.bearblog.dev/needle-in-the-haystack/
**Author**: Devansh
**Results**: ~112 CVEs found, ~$4,000 API credits (Firefox + multiple projects)

---

## Core thesis

"Minimal strategic scaffolding + maximum targeted research" > mega-prompt > no structure.

Context length is the enemy. As context grows, model reliability drops — a single invariant violation buried in thousands of lines of legitimate code gets missed.

---

## Context Rot problem

When the "needle" (vulnerability) is a single invariant violation buried in thousands of lines of legitimate code, long contexts cause the model to:
- Generate theoretical vulnerabilities in unreachable code paths ("breadth-first hallucination")
- Miss the actual vulnerability due to attention dilution
- Produce false positives without checking attacker accessibility

**Implication**: Prioritize and slice before feeding to LLM. Never dump the whole codebase.

---

## Token budget distribution

```
< 10%   — stable scaffolding: threat model, trust boundaries, invariant list
60-80%  — focused audit of individual slices in narrow contexts
20-30%  — verifier loops: tests, fuzzing, PoC reproduction, patch validation
```

---

## Code slicing

Instead of auditing the entire codebase, split into thin slices:
- Authentication / authorization
- Session management
- Request parsing
- File uploads / deserialization
- Sandbox boundaries
- Plugin interfaces

Each slice gets its own threat model and targeted research. Same as our `priority_targets` from Stage 1.

---

## 10 prompting techniques for vulnerability finding

### 1. Assert existence
"This function definitely has 2-3 security issues" > "is this vulnerable?"
Redefines model's optimization from evaluation to discovery.

### 2. Require PoC, not assessment
"Write an HTTP request that bypasses this validation" > "is this validation sufficient?"
Forces concrete, testable output.

### 3. Red team framing
"You are paid to find real exploitable vulnerabilities, not theoretical ones."
Shifts priority from coverage to impact.

### 4. False anchoring
"I already found one vulnerability, find the rest."
Creates social proof that code is genuinely buggy.

### 5. Question inversion
"How would you break this?" > "Is this secure?"
Inverted prompts yield 2-3× more valid findings.

### 6. Invariant decomposition
First: list all assumptions of the function.
Then: check each invariant independently.

### 7. Developer error assumption
"Assume the developer introduced a bug here."
Blocks model's tendency to rationalize code as correct.

### 8. Comparative prompts
"How does this differ from a standard secure implementation of this pattern?"

### 9. Iterative escalation
After first findings: "What more subtle issues are easy to miss?"
Pushes model into the tail of the completion distribution — less obvious, more valuable findings.

### 10. Explicit attacker model
"You are a remote unauthenticated attacker with access only to the public API."
Eliminates false positives, forces creative search within constraints.

---

## Threat model as compression algorithm

> "Creating a threat model before auditing is the most efficient form of compression for security research."

Optimal scaffolding: 1-page threat model + short list of critical functions + small set of invariants.

NOT: 20-page Agent.md with policies and style guides.

---

## Real CVE examples (2026)

### Parse Server
- CVE-2026-29182/30228/30229: Three auth vulnerabilities where `isMaster` check existed but was ignored for `readOnlyMasterKey`
- CVE-2026-30863: JWT audience validation bypass when config was incomplete

### HonoJS
- CVE-2026-22817: Fallback to HS256 when no algorithm pinning → sign tokens with public key as HMAC secret
- CVE-2026-22818: JWKS middleware trusted `header.alg` when `alg` missing from JWK

### ElysiaJS
- Cookie signature bypass: `let decoded = true` instead of `false` in signature rotation logic

### BullFrog
- DNS pipelining bypass: parser checked only first message in TCP segment
- Sudo bypass: Docker group membership persisted after sudoers removal

---

## Implications for SR-agent

### Stage 1 (Discovery)
Context rot validates our SIG prioritization approach — slice before sending to LLM.

Stage 1 system prompt should explicitly build threat model:
1. Analyze contract's past known vulnerabilities (if any)
2. Identify trust boundaries (who can call what)
3. Map critical operations: mints, transfers, upgrades, approvals
4. List invariants that must hold (e.g., "total minted ≤ cap")

### Stage 2 (CheckRunner) system prompt improvements

Apply prompting techniques 1, 2, 3, 5, 10:

```
Current: "Analyze {target} for security issues."

Better:
"You are a paid red-team researcher. This function contains 1-3 exploitable 
vulnerabilities — your job is to find them, not decide if they exist.

Attacker model: remote unauthenticated user, access to public-facing functions only.

For each vulnerability found:
1. Write the exact transaction/calldata that triggers it
2. State which invariant is violated
3. Calculate maximum extractable value

How would you break {function_name}?"
```

### Stage 3 (Synthesis)
Iterative escalation (technique 9): after Stage 2 findings, ask "what subtle issues are easy to miss when these findings are already known?"

### Verification (Phase 8)
Author's verifier loop maps to our PoC pipeline:
- Unit/integration tests
- Sanitizer builds
- Lightweight fuzzers
- Static analysis (Slither)
- Policy checks ("authz must gate these endpoints")

### Token budget
Our `token_budget_used` tracking in `AuditSession` aligns with author's distribution.
Target: Stage 1 < 10%, Stage 2 60-80%, Stage 3 + PoC 20-30%.

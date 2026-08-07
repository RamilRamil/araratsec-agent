# Relay Architecture — Decoupling the Agent from a Live LLM API

**Type**: Design decision record (original)
**Author**: Ramil Mustafin (bronto)
**Status**: Accepted — decisions B / B / middle / yes (see Forks)

**Related**:
- [[secure-rlm-design]] — same principle: orchestrator is the boundary, model is pluggable
- Phase 6 confirmation channel — the async-file pattern this reuses
- file_bridge.py (T058), `external_llm_output` source type — already anticipated this

---

## Context / constraint

- No Claude API access now, and likely none for the foreseeable future.
- Codex API expected eventually.
- From Claude (chat), analysis-result files will be brought into the project **manually**.

The agent must therefore not depend on a synchronous Claude API key, while keeping
the deterministic Orchestration Plane and its security properties intact.

---

## Core reframe

The LLM is a **pluggable reasoning provider** behind one interface:

```
provider.complete(messages) -> AgentAction        # or analysis -> list[Finding]
```

The orchestrator (deterministic) is the security boundary; the provider is an oracle
behind it. Backends of the same interface:

| Backend | Status | Transport |
|---|---|---|
| `CodexClient` | future | synchronous API |
| `RelayBridge` | **now** | asynchronous file channel (human carries files) |
| `ClaudeClient` | if API ever appears | synchronous API |

The existing `ModelRouter` already routes per stage (`TaskType`), so different stages
can use different backends with no change to the loop.

---

## The four forks — decisions

### Fork 1 — Control model: does Claude DRIVE the loop or FEED it? → **B (feed)**

Claude is a **batch analysis engine**, not a step-by-step ReAct driver.

- The orchestrator does planning deterministically (SIG → which functions to look at).
- It emits per-target analysis requests; Claude returns findings; the orchestrator
  ingests them through the guardrails.
- Rationale: much of the "reasoning" is already deterministic in this codebase —
  `guardrails/severity.py` (conjunction check), `guardrails/escalation.py`, the SIG
  filter for Stage 3. The LLM is genuinely needed only for Stage 1 (what looks
  suspicious) and Stage 2 (per-target vulnerability analysis).

Rejected (A): relaying one `AgentAction` per ReAct step — 50 steps = 50 copy-pastes,
and forces Claude to emit rigid action JSON. High toil, no benefit here.

### Fork 2 — Blocking vs checkpoint-resume → **B (checkpoint-resume)**

Relay turnaround is human-time (minutes to days), so the orchestrator must not block
a process waiting.

- The orchestrator writes relay requests, then **exits cleanly** (checkpoint saved).
- The human does the analysis at their own pace.
- `sr-agent resume` ingests the responses and continues.

This splits the two channels by semantics:
- **confirm** = synchronous human *decision* (seconds) → stays blocking (Phase 6)
- **relay** = asynchronous *transport of reasoning* (hours) → resumable

Reuses the existing checkpoint mechanism (`orchestrator/checkpoint.py`).

### Fork 3 — Response format: strict JSON vs free-form → **middle (defined-but-forgiving)**

Claude is given a template and returns findings as a **fenced JSON block**. A tolerant
adapter:
1. extracts the fenced block (ignores surrounding prose),
2. validates each entry into a `Finding` (strict on the schema that matters),
3. sanitizes `notes` (guardrails/sanitize.py),
4. on a malformed/missing block → not a crash, but a re-request (fail-safe, like
   confirmation timeout).

Strict where it matters (the Finding schema), forgiving about the chat prose around it.

### Fork 4 — Per-stage provider routing → **yes**

Keep `ModelRouter` routing per stage:

```
Stage 1 (planning)        → deterministic SIG, no LLM where possible
Stage 2 (per-target)      → relay (Claude) now / CodexClient later
Stage 3 (combination)     → SIG filter + conjunction check (already deterministic)
```

When Codex arrives, only the Stage 2 route changes; the loop is untouched.

---

## Critical security rule: RELAY ≠ AUTHORING

The tempting mistake: "I pasted Claude's answer myself, so it's `human_input` (trust 4)."
**No.** The human is a *transport*, not the author — they may not have scrutinised every line.

```
Relaying an LLM response   → source_type = external_llm_output (trust 2)
Making a decision yourself  → separate channel (sr-agent confirm) → human_input (trust 4)
```

Consequences:
- A relayed finding that says "mark verified_safe" is still blocked by the status gate,
  because relayed content is `external_llm_output`, not `human_input`.
- All deterministic guards (whitelist, path containment, status gate, severity
  conjunction, sanitize) apply to relayed content exactly as to any LLM output.
- Genuine human authority requires a separate explicit action, never a side effect of
  dropping a file.

Relay does **not** weaken the security model — the orchestrator never trusted LLM
output anyway. The relay is just a different transport for the same untrusted oracle.

### Provenance honesty in relay mode

The orchestrator cannot cryptographically prove a relayed file came from Claude (the
chat/human has no HMAC secret). The trust boundary is the human transport. What the
orchestrator still guarantees: schema validation, all guardrails, and
`external_llm_output` provenance. So a garbled or malicious relayed response cannot
escape the Orchestration Plane.

---

## Resulting flow

```
sr-agent audit ./contracts
   ↓
Stage 1: deterministic SIG planning → priority targets
   ↓
For each target: RelayBridge writes relay/requests/{id}.md
   (wrapped context + Finding schema + copy-paste instruction)
   ↓
orchestrator checkpoints and EXITS
   ↓
[human] paste each request into Claude → save responses to relay/responses/{id}.json
   (Stage 2 targets are independent → do them in one Claude session, BATCH)
   ↓
sr-agent resume
   ↓
adapter: extract fenced JSON → validate Finding → sanitize → write to memory
   (source_type = external_llm_output)
   ↓
Stage 3: SIG filter + conjunction check (deterministic) → combined findings
   ↓
report
```

---

## What to build (and why it needs no API)

`RelayBridge` is fully deterministic — testable now, like the confirmation channel:

1. `orchestrator/relay.py` — `request_analysis(target, context, relay_dir)` writes the
   request packet; `ingest_response(id, relay_dir) -> list[Finding]` reads + adapts +
   validates. Mirrors confirmation.py.
2. `cli.py` — `sr-agent relay --show <id> / --respond <id> <file> / --list`.
3. Adapter — fenced-JSON extractor + `Finding` validation + sanitize.
4. `ModelRouter` — route Stage 2 `TaskType` to `RelayBridge`.

All of this is testable with fixtures (sample Claude responses) — zero API, zero Docker.

---

## Bonus: this is a security feature, not a workaround

"Human relays every reasoning step" = a human is in the loop on every piece of LLM
output, and that output is `external_llm_output`, gated by the full Orchestration Plane.
For a high-assurance audit this is a legitimate operating mode — and a strong narrative:
*no model output reaches an action without passing through a human and the deterministic
guards.*

# Secure RLM: Hardening Recursive Language Models against Memory Injection

**Type**: Original design proposal (not a paper summary)
**Author**: Ramil Mustafin (bronto)
**Status**: Design exploration for SR-agent Stage 2 scaling

**Background reading**:
- [[recursive-language-models]] — the RLM paradigm this hardens
- [[devansh-needle-haystack-llm-vulns]] — context rot, the problem RLM solves
- [[composable-security-prompt-injection-mistakes]] — why one checker is not enough
- [[aiuc-1-rag-controls]] — content-integrity controls applied to retrieved chunks

---

## Problem

Recursive Language Models (RLM) solve context rot by treating a long prompt as an
external environment: the main model gets a persistent Python REPL, slices the input
programmatically, and calls sub-LLMs on chunks. Powerful — 4-5× token efficiency,
handles ~300-400k tokens where a vanilla LLM scores zero.

But from a Memory-Injection / prompt-injection standpoint, vanilla RLM is a large new
attack surface:

1. **Indirect injection** — the long input is untrusted; a payload in it can steer the
   Python the main model writes.
2. **Code execution** — a persistent REPL can touch filesystem, network, processes.
3. **Recursive compounding** — an injected instruction can propagate and amplify across
   recursion levels via sub-LLM calls.
4. **Self-written code** — the model executes code it generated from (poisoned) input.

This is the opposite of SR-agent's design rule: the LLM never executes free-form code,
only typed `ActionType` validated by the orchestrator.

---

## Core principle: a checker model lowers probability, it is not the boundary

A checker model is itself an LLM. Putting an LLM in front of an LLM stacks two
probabilistic filters — it reduces Attack Success Rate but never to zero. Same lesson as
fine-tuning (ASR 85% → 1.7%, never 0).

So the question is not "add a checker — yes/no" but **"where do checkers go, and what
deterministic floor do they sit on top of?"**

---

## Control points in the RLM loop

```
untrusted prompt
   ↓  [A] input checker — scan chunks before they enter sub-LLM context
main model writes Python
   ↓  [B] code checker — validate code BEFORE execution
REPL execution + sub-LLM calls
   ↓  [C] output checker — inspect sub-LLM result before it re-enters main context
aggregation → answer
   ↓  [D] action checker — if a sub-LLM emits a side effect
```

| Point | Catches | Right tool |
|---|---|---|
| **A** input | injection in retrieved chunks | ✅ fine-tuned attack detector + `sanitize` + `[DATA START]` |
| **B** code | model wrote malicious Python | ❌ NOT a classifier → deterministic AST allow-list + sandbox |
| **C** sub-LLM output | injection compounding across recursion | ✅ fine-tuned attack detector |
| **D** side effect | sub-LLM tries to act | ❌ typed `ActionType` + orchestrator validation |

**Key split**: a fine-tuned attack-detector belongs at **A and C** (content inspection —
"does this text contain an injection attempt?"). It is the *wrong* tool at **B** —
validating arbitrary code with an LLM is weak (rephrasing, obfuscation, splitting evade
it). B needs determinism: allow-listed operations, no network/FS, resource limits.

---

## Who guards the guard?

The checker receives untrusted input, so it is itself a target. Two rules to keep it from
being hijacked:

1. **The checker is a classifier, not a generative judge.** Output is a score (0..1),
   not text. A model that can only return a number has nowhere to inject an executable
   instruction. A generative "evaluate and explain" judge is an open door.

2. **The checker is fully isolated**: no tools, no memory access, fixed prompt, no
   history. One input → one score. Stateless.

---

## Honest limits

- **Generalization gap** — trained on known attacks; novel patterns absent from training
  pass through. This is the needle-in-haystack problem: novelty defeats recognition.
- **Adversarial evasion** — any fixed detector can be targeted deliberately. Requires
  continuous eval against fresh attacks (regression gate, Phase 9).
- The checker is therefore **ASR reduction + raised attack cost**, measurable on an eval
  dataset. A *layer*, not *the* defense.

---

## Secure RLM for SR-agent Stage 2

Reuse what is already designed. The orchestrator — not the LLM — does the slicing.

```
Large contract (exceeds Stage 2 window)
        ↓
Orchestrator (deterministic) slices by SIG     ← NOT model-written Python
        ↓
for each slice:
   sanitize() + [DATA START]                    ← input
   checker classifier (Qwen-MI-detect)          ← point A, fine-tuned
        ↓
   Stage 2 sub-LLM analyzes slice
        ↓
   AgentAction schema validation                ← point D, typed output
   checker on output                            ← point C
        ↓
Orchestrator aggregates findings (append-only + HMAC)
```

**Difference from vanilla RLM**: slicing is done by the deterministic orchestrator over
the SIG, not by an LLM writing arbitrary Python. We keep RLM's efficiency (parallel
sub-LLMs over chunks) but remove its dangerous freedom (REPL + self-written code).

We trade some of RLM's flexibility (it can't invent novel slicing strategies on the fly)
for a bounded blast radius. For a security auditor, that trade is correct.

---

## Ties to Phase 10 (fine-tuning pipeline)

Phase 10 already plans to fine-tune Qwen3-4B for Stage 2. This design adds a second,
smaller model:

| Model | Task | Output |
|---|---|---|
| `sr-stage2` (planned) | find vulnerabilities in a slice | structured findings |
| `sr-mi-detect` (new) | detect injection / MI in a chunk | score 0..1 |

Training data for the checker already partially exists:
`tests/security/fixtures/malicious_memories.jsonl` (5 signed MI scenarios) +
`tests/security/fixtures/trigger_queries.txt`. Expand with hard negatives (benign text
that looks suspicious) and novel-attack holdout set for the generalization-gap eval.

---

## Open questions

1. Checker placement cost — running `sr-mi-detect` on every chunk boundary adds latency.
   Batch it? Run only on chunks flagged by cheaper heuristics first?
2. Score threshold — where to cut? Tunable per audit risk level (Society/Security pillar
   of AIUC-1)?
3. Should a checker hit be a hard block, or an escalation trigger (route to human)?
   Leaning escalation — a hard block gives the attacker a tamper oracle (cf. silent-drop
   reasoning in episodic memory).

# pkqs91: $200k Web3 Bug Bounties with Codex

**Source**: https://x.com/pkqs91/status/2070157806104457395
**Author**: pkqs91 (independent security researcher)
**Context**: Practical account of using OpenAI Codex as an AI audit agent for web3 bug bounties

---

## Key numbers

- $200,000 from web3 bug bounties using AI-assisted workflow
- 6 ChatGPT Pro accounts at peak ($1,200/month) — ~$14,500 estimated API cost over 7 days
- Targets: EVM contracts, Solana, Cosmos, ZK systems, bridges

---

## 3-step workflow

```
Intake    → messy target → local research bundle
           (scope, severity rules, exclusions, docs, code, context)

Hunting   → explore wide, exploit deep
           (parallel pattern scouts → adaptive lead bank → deep chain tracing)

Verification → kill most candidates
              (scope check, guard check, economic feasibility, impact check)
```

---

## "Explore wide, exploit deep" — core mental model

**Explore wide**: cover maximum surface area in parallel
- Assets, entrypoints, trust boundaries, invariants
- Known patterns AND boring corners
- Downside: most leads are weak / out of scope / not exploitable

**Exploit deep**: take one promising lead and push to real impact
- Loss of funds? Unauthorized minting? Chain crash? Governance manipulation?
- Each lead must earn its way to concrete impact

This is a pull, not push model — weak leads die fast, strong leads get more resources.

---

## 5-part core loop

1. **Problem frame** — scope + docs + code + severity rules + semantic map + **impact map**
   - "Find bugs" is too vague
   - Agent needs to know what impact actually matters for THIS target

2. **Parallel exploration** — pattern scouts split target by surface area
   - Each scout has a trigger shape to look for
   - Accounting edges, parser weirdness, trust-boundary mistakes, docs/code mismatches

3. **Adaptive lead bank** — weak signals merged, ranked, killed, or promoted
   - Reallocate attention instead of treating every lead equally
   - Demote leads that die, promote leads that deepen

4. **Parallel deepening** — each chain trace: attacker input → impact sink
   - Required output: input + trust boundary + state transition + broken invariant + impact + missing proof

5. **End-to-end testing** — only strongest candidates reach this gate
   - Can the path be reproduced and defended?

---

## Verification questions (kills most candidates)

1. Is it in scope?
2. Is the entrypoint really attacker-accessible?
3. Does the attack require a privileged role to make a mistake?
4. Is there an on-chain guard that kills the path?
5. Is the attack economically feasible?
6. Does the impact actually matter?

**Rule**: If you cannot explain the finding, reproduce it, and defend the impact — don't submit.

---

## What didn't work

**Too many bug patterns** → shallow analogies → output becomes noise
- First version was worse than "Find all bugs, make no mistakes"
- Patterns help only when they're precise, not when they're a checklist

**No eval dataset** → can't tell if you improved
- "You change a prompt, run it on a new target, see different output, think you improved. Most of the time you did not. You just made it different."
- Every change needs a regression test

**Model upgrades mattered most**
- Sometimes biggest improvement wasn't harness rewrite — it was the model getting better

---

## Bug bounty vs full audit — different goals

| | Bug bounty | Full audit |
|---|---|---|
| Goal | Find ONE high-impact bug | Broad coverage |
| AI fit | High — parallel threads, kill junk fast | Lower — researcher responsible for coverage |
| Workflow | Explore wide → kill most → verify few | Systematic, can't skip areas |

---

## Implications for SR-agent

### What we have
- Stage 1 (Discovery) with SIG prioritization ✓
- Stage 2 (CheckRunner) per-target checklist ✓
- Verification questions partially in conjunction check ✓
- Eval infrastructure planned (Phase 9) ✓

### What this suggests adding

**Impact map in AuditInput**
Currently we have `focus_files` and `exclude_paths` but no explicit "what counts as critical impact for this protocol". pkqs91's harness knew whether loss-of-funds or governance manipulation was the priority — changes how leads are ranked.

**Adaptive lead bank in Stage 1**
Our Stage 1 produces a static priority list from SIG. A dynamic version would demote leads that come back clean from Stage 2 and promote leads that show partial precondition matches.

**Verification questions as Stage 2 checklist**
pkqs91's 6 verification questions map directly onto our precondition framework. Questions 3 and 4 (privileged role + on-chain guard) correspond to our `mitigations_present` field.

**Parallel exploration**
pkqs91 ran pattern scouts in parallel. Our Stage 2 is sequential (for-loop). For large codebases, parallel Stage 2 workers would match this approach.

---
type: Reference
title: The Audit Agent — first capability pack
description: How the audit CapabilityPack plugs into the secure-agent-kernel, what it adds, and how it is constrained.
tags: [audit-agent, capability-pack, kernel, architecture]
lang: en
status: stable
generated:
  by: human:ramilmustafin
  at: 2026-08-07T21:02:02+04:00
sources:
  - resource: audit_agent/pack.py
    title: AUDIT_PACK assembly
---

# The Audit Agent — the first capability pack

The audit agent is **not** a separate program; it is a **capability pack** that plugs
the kernel into one task: smart-contract security auditing. Everything task-specific
lives under `sr_agent/packs/audit/` and reaches the kernel through the single
[`CapabilityPack`](https://github.com/RamilRamil/secure-agent-kernel) interface. Remove the pack
and the [kernel](https://github.com/RamilRamil/secure-agent-kernel) still stands, task-agnostic; swap in a different pack and
the same security guarantees apply to a different domain.

Its purpose is twofold: **do the audit work**, and by doing it, **demonstrate that the
kernel's security holds under a real, adversarial workload** (it audits attacker-authored
contracts and ingests untrusted tool output all day).

## What the pack adds

- **Domain model** (`finding.py`) — findings, `Severity`, SIG tags, PoC status. These
  are audit concepts; the kernel never sees them except as opaque payloads it signs.
- **Tools** (`tools/`) — `static_analysis` (Slither/Mythril in the sandbox),
  `smartgraphical` (call-graph / structural analysis), `onchain` (read on-chain state
  via a provider), `write_execute` (write a PoC, run `forge test` — an irreversible,
  confirmation-gated action).
- **Methodology** (`planner/`, `methodology/`, `pipeline.py`) — Discovery,
  Check, and Synthesis are pack actions (`run_discovery`, `run_check`,
  `run_synthesis`, `skip_target`) on `KernelActionExecutor`. Chat and
  `sr-agent audit` share a pure reducer over a kernel `MemorySnapshot`.
  Snapshot over 10000 items / 32 MiB fails closed: `complete_session` and
  continue in a new session. SmartGraphical is off on both surfaces.
- **Reasoning + escalation** (`reasoning.py`, `escalation.py`) — the audit chat system
  prompt and domain escalation triggers, injected into the kernel's generic machinery.
- **Assembly** (`pack.py`) — `AUDIT_PACK`, the `CapabilityPack` the composition roots
  hand to the kernel.

The pack is **constrained by construction**: it can register tools and mark
`write_execute` actions high-risk, but it cannot skip the confirmation gate, forge a
trust tier, or write memory directly — the kernel does the signing and sets the source
tier itself.

## Hard rule: the audited target never enters this repo

The audited/bug-bounty **target code, contract names, findings, and reports live
entirely outside this repository.** The agent reads them from an external project path
at runtime; generated PoCs are written into that external project
(`<target>/audit/poc/`), never here. Examples in this repo use generic names
(`Vault.sol`, `reentrancy`). This keeps the agent a clean, reusable tool and avoids
leaking someone else's code into it.

## What it needs to run

Everything the [kernel needs](https://github.com/RamilRamil/secure-agent-kernel), plus:

- **Docker images** for the analysis/execution tools — `docker/Dockerfile.{slither,
  mythril,foundry}` (the Foundry image bakes `solc` so PoCs compile offline under
  `--network none`).
- **A local coder model** (via Ollama) for local reasoning / PoC drafting, or the relay
  for stronger models. On weak local hardware, host the model on a cloud GPU and point
  `LocalClient` at a tunnel (see [research/cloud-gpu-hosting.md](../research/cloud-gpu-hosting.md)).
- **Optional**: `ALCHEMY_API_KEY` / `TENDERLY_API_KEY` for on-chain audits;
  `SR_SMARTGRAPHICAL_ROOT` for the structural tool; a paid `ANTHROPIC_API_KEY` only if
  you opt into the paid backend (never required).

## How to run it

```bash
export SR_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# Interactive audit chat, bound to an EXTERNAL target folder:
sr-agent chat /path/to/target/contracts --project-id my-project

# Approve a paused write_execute action, out-of-band (separate invocation):
sr-agent confirm <id> --approve

# Inspect signed memory / run the batch pipeline / relay:
sr-agent memory --project my-project
sr-agent --help
```

Two other surfaces drive the same pack:

- **Operator frontend** (`frontend/`) — a single-operator web console (FastAPI + Svelte)
  to run/observe/approve solo, with a model-config panel and a live trace. Same
  `OrchestratorLoop(pack=AUDIT_PACK, …)`, no paid API required. See
  [specs/005-operator-frontend](../specs/005-operator-frontend/).
- **PoC workability runner** (`scripts/poc_queue_runner.py`) — the experiment testing
  whether a local model can autonomously draft proof-of-code for an external report's
  findings end-to-end (detection list + PoC), grounded only in the target's own
  original (git-tracked) code. Run against an external `POC_PROJECT`/`POC_REPORT`.
  Before a run, the **target** needs a usable deploy/PoC scaffold (and RPC for fork
  PASS) — see [poc-target-prerequisites.md](poc-target-prerequisites.md).

## Where the boundary is drawn

See [the secure-agent-kernel repo](https://github.com/RamilRamil/secure-agent-kernel) for the invariants and the `CapabilityPack` interface, and
`specs/004-kernel-pack-boundary/` for how the audit-specifics were extracted behind it
(the architecture test asserts the kernel imports zero pack modules).

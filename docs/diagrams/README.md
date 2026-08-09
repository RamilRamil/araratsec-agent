---
type: Reference
title: Diagrams index
description: Index of architecture and execution-flow diagrams; bilingual EN/RU convention.
tags: [index, diagrams]
lang: en
status: stable
generated:
  by: human:ramilmustafin
  at: 2026-08-07T21:02:02+04:00
---

# Diagrams

Architecture and execution-flow diagrams for SR-agent, reflecting **what is actually
wired up and running today**. Mermaid source, renders in GitHub/VS Code/most markdown
viewers.

**Bilingual docs.** Each doc has an English base file (`name.md`) and a Russian sibling
(`name.ru.md`); they cross-link at the top. Keep the two in sync when the wiring changes.

- [agent-overview-flow.md](agent-overview-flow.md) · [🇷🇺](agent-overview-flow.ru.md) — the
  **whole agent**: the capability pipeline (Discovery → CheckRunner → Synthesis → report) and
  the kernel security axis that wraps it, with the PoC layer as a detached downstream block.
  Marks wired vs vision.
- [poc-lifecycle-flow.md](poc-lifecycle-flow.md) · [🇷🇺](poc-lifecycle-flow.ru.md) — zoom into
  the PoC block: report → per-finding verdict → measurement cascade → quality triage. Marks
  what is wired today (stages 1–13) vs where judgement is still manual (14–15).
- [poc-writing-flow.md](poc-writing-flow.md) · [🇷🇺](poc-writing-flow.ru.md) — the
  `scripts/poc_queue_runner.py` inner loop: the model extracts its own finding list, then draft →
  grounded → compile → fix. Target-side harness/RPC checklist:
  [../poc-target-prerequisites.md](../poc-target-prerequisites.md).
- [architecture-overview.md](architecture-overview.md) · [🇷🇺](architecture-overview.ru.md) —
  module map: the task-agnostic [kernel](https://github.com/RamilRamil/secure-agent-kernel), the [audit pack](../audit-agent.md) that
  plugs into it, the two composition roots (CLI + operator frontend), and the standalone PoC experiment.
- [chat-turn-flow.md](chat-turn-flow.md) · [🇷🇺](chat-turn-flow.ru.md) — one turn of `sr-agent chat`
  through `OrchestratorLoop.run_turn` (DATA-wrapping, validate_action, escalation, OOB pause).

Update these when the wiring changes — a diagram that lies about what's connected is
worse than no diagram.

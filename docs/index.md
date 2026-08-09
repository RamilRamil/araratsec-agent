---
type: Reference
title: araratsec-agent documentation
description: OKF knowledge bundle for the araratsec-agent audit CapabilityPack, its pipeline, and PoC tooling.
okf_version: "0.2"
tags: [index, documentation, audit-agent]
lang: en
status: stable
generated:
  by: araratsec-agent/claude-opus-4.8
  at: 2026-08-07T20:55:00Z
---

# araratsec-agent documentation

This directory is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
(OKF v0.2) bundle: every concept is a Markdown file with YAML frontmatter, versioned in git
alongside the code it describes. Change history is in [log.md](log.md).

**Bilingual convention.** Each concept has an English base file (`name.md`) and a Russian
sibling (`name.ru.md`), cross-linked at the top and carrying `lang: en` / `lang: ru`. Keep
the pair in sync when the wiring changes.

**Provenance.** `generated.by` follows the OKF actor convention: `human:<id>` for
human-authored content, `<producer>/<model>` for agent-drafted content. Agent-drafted docs
have not yet been human-`verified`; add a `verified` entry after review.

## The pack & principles

- [audit-agent.md](audit-agent.md) · [🇷🇺](audit-agent.ru.md) — the audit CapabilityPack on
  the secure-agent-kernel: what it adds and how it is constrained.
- [eval-principles.md](eval-principles.md) · [🇷🇺](eval-principles.ru.md) — positive-signal
  verdicts, corroboration, and operator SOPs against false positives.
- [poc-target-prerequisites.md](poc-target-prerequisites.md) · [🇷🇺](poc-target-prerequisites.ru.md) —
  operator SOP: what the analyzed Foundry project must expose before a PoC run.

## Diagrams (flow & architecture)

- [diagrams/agent-overview-flow.md](diagrams/agent-overview-flow.md) · [🇷🇺](diagrams/agent-overview-flow.ru.md) —
  the whole agent: capability pipeline + kernel security axis; PoC as a detached downstream block.
- [diagrams/poc-lifecycle-flow.md](diagrams/poc-lifecycle-flow.md) · [🇷🇺](diagrams/poc-lifecycle-flow.ru.md) —
  zoom into the PoC block: report → verdict → measurement → quality triage.
- [diagrams/poc-writing-flow.md](diagrams/poc-writing-flow.md) · [🇷🇺](diagrams/poc-writing-flow.ru.md) —
  the inner draft → grounded → compile → fix loop of the PoC runner.
- [diagrams/architecture-overview.md](diagrams/architecture-overview.md) · [🇷🇺](diagrams/architecture-overview.ru.md) —
  module map: kernel, pack, and the composition roots that drive them.
- [diagrams/chat-turn-flow.md](diagrams/chat-turn-flow.md) · [🇷🇺](diagrams/chat-turn-flow.ru.md) —
  one turn of `sr-agent chat` through `OrchestratorLoop.run_turn`.
- [diagrams/README.md](diagrams/README.md) · [🇷🇺](diagrams/README.ru.md) — the diagrams sub-index.

## Related (outside this bundle)

- `../README.md` — project overview and the two-repository split.
- `../poc-target-prerequisites.md` is mirrored here; the operator checklist lives with the docs.

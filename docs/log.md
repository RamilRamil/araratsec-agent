# Changelog

Chronological history for the `docs/` OKF bundle, newest first (OKF v0.2 reserved `log.md`).

## 2026-08-07

- **Fixed layout drift** in `diagrams/architecture-overview` and `diagrams/chat-turn-flow`
  (both EN + RU): the composition-root CLI is `audit_agent/cli.py` (not `sr_agent/cli.py`); the
  pack subgraph is `audit_agent` (not `sr_agent/packs/audit`); `llm_core` lists the real provider
  clients (`claude_client`/`gemini_client`/`openrouter_client`, no `relay`); the dead `../kernel.md`
  link now points to the external `secure-agent-kernel` repo (the kernel was split out, feature 048).
- **Repointed all remaining dead `kernel.md` links** (EN + RU) in `audit-agent`, `eval-principles`,
  and `diagrams/README` to the external `secure-agent-kernel` repo. (Note: `sr_agent/packs/audit`
  path drift in `audit-agent` / `eval-principles` bodies is still open — separate from the link fix.)
- **Adopted OKF v0.2** across `docs/`: YAML frontmatter on every concept, bundle-root
  [index.md](index.md) declaring `okf_version: "0.2"`, and this `log.md`. Provenance seeded
  via `generated.by`/`at` (owner for pre-existing content, agent for session-drafted content).
- **Added** `diagrams/agent-overview-flow` (EN + RU) — the whole-agent flow: capability
  pipeline + kernel security axis, with the PoC layer as a detached downstream block.
- **Added** `diagrams/poc-lifecycle-flow` (EN + RU) — end-to-end PoC block: report → verdict →
  measurement cascade → quality triage (stages 1–13 wired, 14–15 manual).
- **Translated** the remaining bundle to Russian (`.ru.md` siblings): `audit-agent`,
  `eval-principles`, `poc-target-prerequisites`, `diagrams/README`, `diagrams/architecture-overview`,
  `diagrams/chat-turn-flow`, `diagrams/poc-writing-flow`.
- **Landed** the SandboxTimeout crash fix in `scripts/poc_queue_runner.py` (agentic-loop path)
  with a regression test; documented in the PoC-lifecycle flow (stage 9, `run_error`).

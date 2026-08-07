# Diagrams

Architecture and execution-flow diagrams for SR-agent, reflecting **what is actually
wired up and running today**. Mermaid source, renders in GitHub/VS Code/most markdown
viewers.

- [architecture-overview.md](architecture-overview.md) — module map: the task-agnostic
  [kernel](../kernel.md), the [audit pack](../audit-agent.md) that plugs into it, the
  two composition roots (CLI + operator frontend), and the standalone PoC experiment.
- [chat-turn-flow.md](chat-turn-flow.md) — one turn of `sr-agent chat` through
  `OrchestratorLoop.run_turn` (DATA-wrapping, validate_action, escalation, OOB pause).
- [poc-writing-flow.md](poc-writing-flow.md) — the current `scripts/poc_queue_runner.py`
  flow: the model extracts its own finding list, then draft → grounded → compile → fix.

Update these when the wiring changes — a diagram that lies about what's connected is
worse than no diagram.

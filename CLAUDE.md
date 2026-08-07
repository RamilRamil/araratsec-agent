<!-- SPECKIT START -->
This working directory is **araratsec-agent** (Repo B): the audit CapabilityPack
(package `audit_agent`) on **secure-agent-kernel** (Repo A, package `sr_agent`) as a
pinned dependency — see `README.md` ("Two repositories") and `docs/audit-agent.md`.
Dev install: editable sibling `pip install -e ../secure-agent-kernel` (see `pyproject.toml`).

Constitution: `.specify/memory/constitution.md`.
Eval / PoC truthfulness: `docs/eval-principles.md`.
PoC runner target-side harness (scaffold, RPC, what the agent will not bootstrap):
`docs/poc-target-prerequisites.md`. Flow: `docs/diagrams/poc-writing-flow.md`.

Active Speckit feature plan: `specs/001-missing-scaffold-honesty/plan.md` — honest handling &
labeling of missing PoC scaffold prerequisites (absent-base short-circuit → `base-insufficient`;
doc/taxonomy reconciliation). Status: implemented (all tasks done; 233 tests green, awaiting commit).
<!-- SPECKIT END -->

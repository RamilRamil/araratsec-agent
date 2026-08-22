<!-- SPECKIT START -->
This working directory is **araratsec-agent** (Repo B): the audit CapabilityPack
(package `audit_agent`) on **secure-agent-kernel** (Repo A, package `sr_agent`) as a
pinned dependency — see `README.md` ("Two repositories") and `docs/audit-agent.md`.
Dev install: editable sibling `pip install -e ../secure-agent-kernel` (see `pyproject.toml`).

Constitution: `.specify/memory/constitution.md`.
Eval / PoC truthfulness: `docs/eval-principles.md`.
PoC runner target-side harness (scaffold, RPC, what the agent will not bootstrap):
`docs/poc-target-prerequisites.md`. Flow: `docs/diagrams/poc-writing-flow.md`.

Active Speckit feature plan: `specs/004-audit-loop-methodology/plan.md` -
methodology stages as pack actions on `KernelActionExecutor`; pure
`AuditMethodologyService`; chat/batch parity; resume without `Path(".")`.
Status: closed on `main` (#7 goldens, #8 implementation; T001-T060).
Kernel pairing `003-dispatch-result-resume` is merged (`3675bac`).
Feature `003-agent-tool-surface` is implemented. Characterization
goldens are on `main` under `tests/audit/goldens/methodology/` (SC-010).
<!-- SPECKIT END -->

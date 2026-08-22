<!-- SPECKIT START -->
This working directory is **araratsec-agent** (Repo B): the audit CapabilityPack
(package `audit_agent`) on **secure-agent-kernel** (Repo A, package `sr_agent`) as a
pinned dependency — see `README.md` ("Two repositories") and `docs/audit-agent.md`.
Dev install: editable sibling `pip install -e ../secure-agent-kernel` (see `pyproject.toml`).

Constitution: `.specify/memory/constitution.md`.
Eval / PoC truthfulness: `docs/eval-principles.md`.
PoC runner target-side harness (scaffold, RPC, what the agent will not bootstrap):
`docs/poc-target-prerequisites.md`. Flow: `docs/diagrams/poc-writing-flow.md`.

Active Speckit feature plan: `specs/006-capability-consolidation/plan.md` -
status **closed** on branch `006-capability-consolidation`. Ten pure proof
modules live in `audit_agent/proof/`; runner interface contract guarded;
instruments stay outside; `exploit_loop` remains the batch producer; kernel
loop is agent-path authority. Kernel pin `0e4e963`
(`kernel/005-finding-provenance`). pack/004 closed on `main`. **pack/005
proof-loop-closure is unblocked** (006 was its start blocker).
<!-- SPECKIT END -->

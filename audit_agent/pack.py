"""AUDIT_PACK — the one capability pack, assembled (feature 004).

Wires the audit domain's action metadata, tools, statuses, prompt, and callables
into a single `CapabilityPack` the kernel consumes by injection. No registry, no
discovery — `cli.py` imports this and passes it to the loop.

The domain action taxonomy (`AuditActionType`, `ACTION_CLASS_MAP`, `REVERSIBLE`,
the `_validate_params` ladder) and the analyzer tool registry now live IN THIS
pack (`audit_agent.actions` / `audit_agent.tool_registry`) per Constitution III /
feature 002 — the kernel's `Action.action_type` is an open string. The
kernel-generic ids (`read_file`, `search_code`, `write_memory`,
`request_human_confirmation`, `escalate`) are INHERITED from the kernel
(`KERNEL_GENERIC_ACTIONS ∪ pack.actions`), not declared here.
"""
from __future__ import annotations

from audit_agent.actions import (
    ACTION_CLASS_MAP, REVERSIBLE, AuditActionType, _validate_params,
)
from audit_agent.tool_registry import TOOL_REGISTRY
from sr_agent.orchestrator.pack import ActionSpec, CapabilityPack
from audit_agent.dispatch import dispatch, execute_confirmed, persist_finding
from audit_agent.escalation import domain_escalation
from audit_agent.reasoning import AUDIT_CHAT_SYSTEM, signal_from

# Domain action id → its class/reversibility/param-validator. DOMAIN ids only —
# the kernel-generic ids are inherited (KERNEL_GENERIC_ACTIONS ∪ pack.actions,
# D4/D6). The confirmation requirement is NOT here — the kernel derives it from
# action_class (FR-005).
AUDIT_ACTIONS: dict[str, ActionSpec] = {
    t.value: ActionSpec(
        action_class=ACTION_CLASS_MAP[t],
        is_reversible=REVERSIBLE[t],
        validate_params=_validate_params,
    )
    for t in AuditActionType
}

# Statuses whose change requires out-of-band human confirmation (Constitution II).
AUDIT_PRIVILEGED_STATUSES = frozenset({"verified_safe", "skip_analysis", "audit_complete"})


AUDIT_PACK = CapabilityPack(
    name="audit",
    actions=AUDIT_ACTIONS,
    tools=tuple(TOOL_REGISTRY.values()),
    privileged_statuses=AUDIT_PRIVILEGED_STATUSES,
    reasoning_prompt=AUDIT_CHAT_SYSTEM,
    dispatch=dispatch,
    execute_confirmed=execute_confirmed,
    persist_finding=persist_finding,
    domain_escalation=domain_escalation,
    signal_from=signal_from,
)

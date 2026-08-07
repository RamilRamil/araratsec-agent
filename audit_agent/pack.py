"""AUDIT_PACK — the one capability pack, assembled (feature 004).

Wires the audit domain's action metadata, tools, statuses, prompt, and callables
into a single `CapabilityPack` the kernel consumes by injection. No registry, no
discovery — `cli.py` imports this and passes it to the loop.

The action metadata (ActionType, ACTION_CLASS_MAP, REVERSIBLE) and the per-action
`_validate_params` are still kernel-located (models/action.py, orchestrator/
action.py) and imported here (pack→kernel is allowed). Moving them into the pack
is a deferred, boundary-clean follow-up (needs a generic `Action.action_type`).
"""
from __future__ import annotations

from sr_agent.models.action import ACTION_CLASS_MAP, ActionType, REVERSIBLE
from sr_agent.orchestrator.action import _validate_params
from sr_agent.orchestrator.pack import ActionSpec, CapabilityPack
from audit_agent.dispatch import dispatch, execute_confirmed, persist_finding
from audit_agent.escalation import domain_escalation
from audit_agent.reasoning import AUDIT_CHAT_SYSTEM, signal_from
from sr_agent.tools.registry import TOOL_REGISTRY

# Domain action id → its class/reversibility/param-validator. The confirmation
# requirement is NOT here — the kernel derives it from action_class (FR-005).
AUDIT_ACTIONS: dict[str, ActionSpec] = {
    t.value: ActionSpec(
        action_class=ACTION_CLASS_MAP[t],
        is_reversible=REVERSIBLE[t],
        validate_params=_validate_params,
    )
    for t in ActionType
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

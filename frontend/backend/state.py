"""Read-only projections of kernel/pack state (feature 005).

Pure reads — NEVER writes memory. Renders what the kernel/pack already hold:
health, modules, and the HMAC episodic memory. Domain data (findings/checkpoints/
status) is pack-produced; generic panels here are pack-agnostic.
"""
from __future__ import annotations

from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.pack import AUDIT_PACK

from frontend.backend.model_config import CONFIG

# The kernel invariants a pack cannot weaken — shown in the architecture/help view.
KERNEL_INVARIANTS = [
    "Every re-entering artifact is DATA-wrapped and never obeyed as an instruction",
    "SourceType trust hierarchy; model/relay output never promoted to human_input",
    "HMAC append-only memory; failing records silently dropped",
    "Out-of-band confirmation gate, kernel-derived from action_class (write_execute ⇒ confirm)",
    "Per-turn tool-call budget",
    "Path-containment + network-isolated ephemeral sandbox for attacker-influenced execution",
]


def health() -> dict:
    """model ready (deep probe) vs available (liveness), + which model/endpoint."""
    client = CONFIG.local_client()
    available = client.available()
    ready = client.ready() if available else False
    return {
        "model_name": client.model,
        "endpoint": CONFIG.endpoint,
        "backend": CONFIG.backend,
        "model_available": available,   # liveness (tags reachable)
        "model_ready": ready,           # can produce output now (ready ≠ reachable)
        "ollama_reachable": available,
    }


def modules() -> dict:
    """The active pack + its tools + the kernel invariants (US5)."""
    return {
        "kernel": "sr_agent (task-agnostic secure kernel)",
        "active_pack": AUDIT_PACK.name,
        "pack_tools": [
            {"name": t.name, "action_class": t.action_class, "description": t.description}
            for t in AUDIT_PACK.tools
        ],
        "kernel_invariants": KERNEL_INVARIANTS,
    }


def domain_panels(memory: EpisodicMemory, session_id: str, project_id: str) -> dict:
    """Pack-produced domain panels (US5/FR-017, SC-008).

    The generic panels above are pack-AGNOSTIC. Domain content comes from the
    active pack: today the audit pack contributes the findings/PoC roadmap — a
    regenerable, read-only VIEW over append-only memory (never a parallel store).
    A second pack would supply its own renderer; this generic surface, tagged by
    pack name, is unchanged. The frontend is an audit-aware composition root
    (imports AUDIT_PACK like cli.py), so it wires the audit renderer here."""
    from sr_agent.orchestrator.chat_session import render_roadmap
    return {
        "pack": AUDIT_PACK.name,
        "panels": [
            {
                "title": "Findings / PoC roadmap",
                "kind": "markdown",
                "body": render_roadmap(session_id, project_id, memory),
            },
        ],
    }


def memory_records(memory: EpisodicMemory, project_id: str) -> list[dict]:
    """Read-only HMAC memory browser (US3). Records failing verification are
    already dropped by the kernel; we only render what verifies."""
    from sr_agent.models.principal import Principal
    records = memory.load_for_principal(Principal(user_id="ui", platform="cli", project_id=project_id))
    out = []
    for r in records:
        if r.finding is not None:
            kind, body = "finding", r.finding
        elif r.checkpoint is not None:
            kind, body = "checkpoint", r.checkpoint
        elif r.status_change is not None:
            kind, body = "status_change", r.status_change.model_dump() if hasattr(r.status_change, "model_dump") else r.status_change
        elif getattr(r, "payload", None) is not None:
            kind, body = getattr(r, "payload_kind", "payload"), r.payload
        else:
            continue
        out.append({
            "kind": kind,
            "source_type": r.source_type.value,
            "target": r.target,
            "session_id": r.session_id,
            "body": body,
        })
    return out

"""Audit capability pack — smart-contract security audit.

The first (and currently only) capability pack. Assembles `AUDIT_PACK`
(`pack.py`) from the audit action types, tools, finding models, planner stages,
domain escalation triggers, privileged statuses, and reasoning prompts. The
kernel consumes it via the `CapabilityPack` interface; `cli.py` wires it in.
"""

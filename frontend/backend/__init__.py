"""Operator frontend backend (feature 005).

A FastAPI app that imports sr_agent + AUDIT_PACK as a SECOND operator surface
(a composition root, like cli.py) — not a new decision path. It renders kernel
state and gates actions through the same kernel primitives. The only kernel
change this feature makes is an additive, optional observability hook
(OrchestratorLoop.event_sink); everything else lives here.
"""

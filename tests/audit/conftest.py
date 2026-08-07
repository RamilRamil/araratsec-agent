"""Shared setup for the audit-side test tree (feature 048, T015).

These tests import the audit pack, which pulls in `sr_agent.config` (via
`audit_agent.config`); the kernel config requires `SR_SECRET_KEY` at
import time. Set a deterministic test key here so `tests/audit/**` collects and
runs standalone — including in Repo B after the carve, where this conftest
travels with the audit tests. `setdefault` never overrides a real exported key.
"""
from __future__ import annotations

import os

os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

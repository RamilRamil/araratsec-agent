"""Ctrl-D detaches; complete/abandon are explicit (FR-024)."""
from __future__ import annotations

from pathlib import Path

_CLI = Path(__file__).resolve().parents[3] / "audit_agent" / "cli.py"


def test_eof_maps_to_detach_and_explicit_commands():
    source = _CLI.read_text(encoding="utf-8")
    assert "detach_session" in source
    assert "complete_session" in source
    assert "abandon_session" in source
    assert "reacquire_lease" in source
    assert "takeover_lease" in source
    assert "rebind_scope" in source
    assert "pending turn: detach refused" in source

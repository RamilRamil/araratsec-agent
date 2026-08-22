"""CLI resume path must invoke resume_turn, not run_turn (FR-018)."""
from __future__ import annotations

from pathlib import Path

_CLI = Path(__file__).resolve().parents[3] / "audit_agent" / "cli.py"


def test_cli_resume_calls_resume_turn_not_run_turn():
    source = _CLI.read_text(encoding="utf-8")
    assert 'loop.resume_turn("audit.reasoning")' in source
    assert "resume is not wired yet" not in source
    # The resume branch must not start a fresh user-message turn.
    resume_idx = source.find("if resume_session:")
    assert resume_idx != -1
    assert "run_turn(user_message)" not in source[resume_idx:resume_idx + 2500]

"""Resume must not invent scope from cwd (SC-002 / SC-004)."""
from __future__ import annotations

from pathlib import Path

_CLI = Path(__file__).resolve().parents[3] / "audit_agent" / "cli.py"


def test_resume_branch_has_no_path_dot():
    source = _CLI.read_text(encoding="utf-8")
    resume_idx = source.find("if resume_session:")
    else_idx = source.find("else:", resume_idx)
    resume_block = source[resume_idx:else_idx]
    assert 'Path(".")' not in resume_block
    assert "Path('.')" not in resume_block


def test_cli_has_no_not_wired_notice():
    source = _CLI.read_text(encoding="utf-8")
    assert "resume is not wired yet" not in source

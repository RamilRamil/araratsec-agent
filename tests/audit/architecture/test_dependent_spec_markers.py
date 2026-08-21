"""Dependent-spec lock: 004/005 inherit 003 finding-grounding rules."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_dependent_specs_carry_finding_grounding_rules():
    spec_004 = (_ROOT / "specs/004-audit-loop-methodology/spec.md").read_text()
    spec_005 = (_ROOT / "specs/005-proof-loop-closure/spec.md").read_text()
    assert "FR-016" in spec_004
    assert "not analyzer evidence" in spec_004
    assert "FR-008a" in spec_005
    assert "hard start blocker" in spec_005
    assert "FR-019" in spec_005

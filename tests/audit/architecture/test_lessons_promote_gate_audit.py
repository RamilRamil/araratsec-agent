"""Feature 014 US1 / SC-004 (audit-side, feature 048): the audit harness never promotes.

The kernel test tests/architecture/test_lessons_promote_gate.py guards the kernel
orchestrator surface. `scripts/poc_queue_runner.py` is the AUDIT harness — it lives in
Repo B, not the kernel carve — so its promotion gate is asserted here, where the audit
tree is present.
"""
import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_HARNESS = _ROOT / "scripts" / "poc_queue_runner.py"


def _promote_calls(source: str) -> list[int]:
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "promote"
    ]


def test_audit_harness_never_promotes_a_lesson():
    assert _HARNESS.exists(), f"audit harness missing: {_HARNESS}"
    calls = _promote_calls(_HARNESS.read_text(encoding="utf-8"))
    assert calls == [], (
        f"{_HARNESS.relative_to(_ROOT)} calls .promote() at lines {calls} — lesson promotion "
        f"must be out-of-band (sr-agent lessons approve) only (SC-004)")


def test_guard_would_catch_an_injected_promote():
    assert _promote_calls("store.promote('abc123')\n") == [1]

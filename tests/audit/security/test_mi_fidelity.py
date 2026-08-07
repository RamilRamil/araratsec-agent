"""Feature 048 T019 — MI fidelity gate (SC-007).

Before the real ``AUDIT_PACK`` ever leaves the monorepo, the kernel's
fixture-pack MI copy must cover the *same* attack-surface scenarios as the
real-pack copy — otherwise the kernel could "prove" MI resistance against a
weaker surface than the pack actually presents.

This is a monorepo-only cross-check: it compares the two sibling test modules
that only coexist here.

* the KERNEL copy   — tests/security/test_chat_mi_scenarios.py     (FIXTURE_PACK)
* the AUDIT copy    — tests/audit/security/test_chat_mi_scenarios.py (AUDIT_PACK)

The ASR-0 half of SC-007 is enforced by pytest actually running both suites (all
scenarios pass in both). This test adds the structural half: both suites declare
the identical set of scenario functions, so the fixture surface cannot silently
drift narrower than the real one.

After the Phase C carve the kernel copy no longer exists beside this file (it was
carved into Repo A); this test then skips, harmlessly — its job is done once,
in the monorepo, which is exactly when the fidelity guarantee must hold.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_KERNEL_COPY = _REPO / "tests" / "security" / "test_chat_mi_scenarios.py"
_AUDIT_COPY = _REPO / "tests" / "audit" / "security" / "test_chat_mi_scenarios.py"


def _scenario_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def test_kernel_and_audit_mi_suites_cover_the_same_scenarios() -> None:
    if not _KERNEL_COPY.exists():
        pytest.skip("kernel MI copy carved into Repo A — monorepo fidelity gate already satisfied")

    kernel = _scenario_names(_KERNEL_COPY)
    audit = _scenario_names(_AUDIT_COPY)

    assert kernel, "kernel MI copy declares no test_* scenarios"
    assert audit, "audit MI copy declares no test_* scenarios"
    assert kernel == audit, (
        "MI fidelity breach (SC-007): the fixture-pack and real-pack MI suites must cover the "
        f"same scenario classes.\n  only in kernel: {sorted(kernel - audit)}\n  only in audit: "
        f"{sorted(audit - kernel)}"
    )

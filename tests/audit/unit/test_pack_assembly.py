"""Pack-assembly boundary (feature 002, US1): the pack declares its DOMAIN taxonomy
and inherits the kernel-generic ids — it does not re-declare or re-import them.

Asserts the post-relocation shape:
  * `AUDIT_ACTIONS` holds domain analyzer ids ONLY — no machinery ids (D4), no
    kernel-generic reads `read_file`/`search_code` (D6), no dropped `run_auditor_skill`;
  * `audit_agent.pack` imports the taxonomy/tools from `audit_agent.*`, NOT the
    removed kernel symbols (`ActionType`/`ACTION_CLASS_MAP`/`REVERSIBLE`/
    `_validate_params`/`sr_agent...registry.TOOL_REGISTRY`).
"""
from __future__ import annotations

import ast
from pathlib import Path

from audit_agent.pack import AUDIT_ACTIONS

_PACK_PY = Path(__file__).resolve().parents[3] / "audit_agent" / "pack.py"

_MACHINERY_AND_TERMINALS = {"write_memory", "request_human_confirmation", "escalate", "complete"}
_KERNEL_GENERIC_READS = {"read_file", "search_code"}
_EXPECTED_DOMAIN = {
    "build_graph", "run_slither", "run_mythril", "analyze_transactions",
    "decompile_bytecode", "write_poc", "run_tests", "deploy_test_contract",
    "run_discovery", "run_check", "run_synthesis", "skip_target",
}


def test_audit_actions_are_domain_only():
    ids = set(AUDIT_ACTIONS)
    assert ids == _EXPECTED_DOMAIN, f"AUDIT_ACTIONS drifted: {sorted(ids)}"
    # explicit exclusions (D4 machinery/terminals, D6 reads, dropped run_auditor_skill)
    assert not (ids & _MACHINERY_AND_TERMINALS), "machinery/terminal id leaked into AUDIT_ACTIONS (D4)"
    assert not (ids & _KERNEL_GENERIC_READS), "kernel-generic read leaked into AUDIT_ACTIONS (D6)"
    assert "run_auditor_skill" not in ids, "run_auditor_skill was dropped in feature 002"


def _imported_names(path: Path) -> list[tuple[str, str]]:
    """(module, imported_name) pairs for every `from module import name`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out.append((node.module, alias.name))
    return out


def test_pack_does_not_import_removed_kernel_symbols():
    imports = _imported_names(_PACK_PY)
    forbidden_names = {"ActionType", "ACTION_CLASS_MAP", "REVERSIBLE", "_validate_params"}
    for module, name in imports:
        if module.startswith("sr_agent"):
            assert name not in forbidden_names, (
                f"pack.py imports {name!r} from {module!r} — it must come from audit_agent.* now"
            )
            assert not (module == "sr_agent.tools.registry" and name == "TOOL_REGISTRY"), (
                "pack.py imports the kernel TOOL_REGISTRY — the domain registry lives in "
                "audit_agent.tool_registry now"
            )
    # and it DOES source them from the pack:
    pack_local = {(m, n) for m, n in imports if m.startswith("audit_agent")}
    assert ("audit_agent.actions", "ACTION_CLASS_MAP") in pack_local
    assert ("audit_agent.tool_registry", "TOOL_REGISTRY") in pack_local

"""Live SmartGraphical integration (feature 002, US1).

Runs the real engine. Auto-skips unless SR_SMARTGRAPHICAL_ROOT points at a
SmartGraphical checkout with a usable interpreter, so the suite stays green
without it.
"""
import os
import pytest
from pathlib import Path

from audit_agent.tools.smartgraphical import run_smartgraphical

_SG_ROOT = os.environ.get("SR_SMARTGRAPHICAL_ROOT", "")


def _sg_ready() -> bool:
    if not _SG_ROOT:
        return False
    return (Path(_SG_ROOT) / ".venv" / "bin" / "python").exists()


pytestmark = pytest.mark.skipif(
    not _sg_ready(), reason="SmartGraphical not configured (SR_SMARTGRAPHICAL_ROOT)"
)


def test_smartgraphical_finds_logic_issue_and_inheritance_graph():
    root = Path(__file__).resolve().parents[2] / "examples" / "inheritance-vault"
    findings, graph = run_smartgraphical(root / "Vault.sol", root, _SG_ROOT)

    rule_ids = {f.rule_id for f in findings}
    # A logic-level ordering finding that Slither/Mythril do not produce.
    assert "check_order" in rule_ids, f"no logic finding in {rule_ids}"

    # The structural graph captures the inheritance call boundary.
    edge_kinds = {e.get("kind") for e in graph.get("edges", [])}
    assert "cross_type_call" in edge_kinds, f"no inheritance edge in {edge_kinds}"

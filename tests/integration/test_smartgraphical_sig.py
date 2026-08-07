"""SmartGraphical graph -> SIG -> Stage 3 combination (feature 002, US2).

Deterministic (uses the stored graph fixture, no live SmartGraphical): findings
on a child function and an inherited parent function that share state are linked
by Stage 3 through the SmartGraphical-built SIG — a combination the single-file
regex SIG does not make.
"""
import json
from pathlib import Path

from audit_agent.finding import Finding, Severity
from audit_agent.planner.sig import build_sig, build_sig_from_smartgraphical
from audit_agent.planner.stage3 import run_stage3

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "smartgraphical"
_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "inheritance-vault"


def _f(fid: str, fn: str) -> Finding:
    return Finding(finding_id=fid, location=f"Vault.sol:{fn}", function_name=fn,
                   severity=Severity.high)


def test_sg_graph_links_inheritance_findings():
    graph = json.load((_FIXTURES / "sample_graph.json").open())
    sig = build_sig_from_smartgraphical(graph)

    a, b = _f("A-1", "deposit"), _f("B-1", "_credit")
    run_stage3([a, b], sigs={"Vault.sol": sig})
    assert "B-1" in a.combined_with     # linked via inherited shared state
    assert "A-1" in b.combined_with


def test_regex_sig_does_not_link_them():
    regex_sig = build_sig((_EXAMPLE / "Vault.sol").read_text())
    a, b = _f("A-1", "deposit"), _f("B-1", "_credit")
    run_stage3([a, b], sigs={"Vault.sol": regex_sig})
    assert a.combined_with == []        # regex SIG misses the inherited link

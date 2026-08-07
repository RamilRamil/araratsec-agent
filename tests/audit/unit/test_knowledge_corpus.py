"""Audit knowledge-corpus content test (extracted from tests/unit/test_knowledge.py, feature 048).

`KnowledgeBase` is a kernel primitive (covered by kernel unit tests with synthetic
fixtures). THIS test asserts the real AUDIT corpus under `knowledge/vulnerability-patterns`
actually ships the seeded reentrancy pattern — that corpus lives in Repo B, not the kernel
carve, so the assertion belongs here.
"""
from pathlib import Path

from sr_agent.memory.knowledge import KnowledgeBase


def test_seeded_pattern_doc_is_searchable():
    root = Path(__file__).resolve().parents[3] / "knowledge"
    kb = KnowledgeBase(root=root)
    results = kb.search("checks effects interactions reentrancy", category="vulnerability-patterns")
    assert results and any("reentrancy" in c.source.lower() for c in results)

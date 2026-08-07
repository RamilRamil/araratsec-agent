"""Feature spec 001 (SC-004): the operator doc, the flow diagram, and the
`scaffold_missing_types` docstring must describe the missing-type check as a GATE and
must carry the correct failure-cause taxonomy (base-insufficient = environment/excluded,
lookup_failed = model/retained). Mechanical guard so the docs cannot silently drift back
to the "diagnostic / may" framing or re-conflate the two terminals.
"""
from __future__ import annotations

import re
from pathlib import Path

import scripts.poc_queue_runner as pqr

_ROOT = Path(__file__).resolve().parents[3]
_PREREQ = _ROOT / "docs" / "poc-target-prerequisites.md"
_FLOW = _ROOT / "docs" / "diagrams" / "poc-writing-flow.md"

# Stale soft-framing of the missing-type gate that must NOT reappear (spec 001 US3).
_STALE = re.compile(r"diagnostic only|not gating|\bmay\b[^.\n]*escalat", re.IGNORECASE)


def test_docs_have_no_stale_diagnostic_framing():
    """NEGATIVE grep: no 'diagnostic only / not gating / may … escalate' in either doc."""
    for doc in (_PREREQ, _FLOW):
        text = doc.read_text(encoding="utf-8")
        assert not _STALE.search(text), f"stale gate framing lingers in {doc.name}"


def test_scaffold_missing_types_docstring_describes_gating():
    """The check's own docstring matches its gating call site (US3 / C6)."""
    doc = pqr.scaffold_missing_types.__doc__ or ""
    assert "GATING" in doc
    assert "not gating" not in doc.lower()


def test_prereq_doc_has_correct_taxonomy_pairing():
    """POSITIVE grep: base-insufficient ↔ environment/excluded AND lookup_failed ↔
    model/retained are both present in the operator doc (not conflated)."""
    text = _PREREQ.read_text(encoding="utf-8")
    assert re.search(r"base-insufficient.*(environment|excluded|harness-infra)", text, re.IGNORECASE)
    assert re.search(r"lookup_failed.*(model|retained|denominator)", text, re.IGNORECASE)


def test_flow_diagram_shows_env_vs_model_split():
    """The diagram carries both terminals with their nature so the split is visible."""
    text = _FLOW.read_text(encoding="utf-8")
    assert re.search(r"base-insufficient.*harness-infra|harness-infra.*base-insufficient", text, re.IGNORECASE | re.DOTALL) or \
        re.search(r"base-insufficient[^\n]*ENVIRONMENT", text, re.IGNORECASE)
    assert re.search(r"lookup_failed[^\n]*model", text, re.IGNORECASE)

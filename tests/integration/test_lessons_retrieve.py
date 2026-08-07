"""Feature 014 US2: retrieve-at-build as suggestion, not control.

DATA-wrapped, inert when empty (byte-identical prompt), lexical fallback (no embedder →
no new dependency). Exercises the harness's `_append_lessons` prompt hook directly.
"""
from pathlib import Path

import scripts.poc_queue_runner as pqr
from sr_agent.memory.lessons import LessonCandidate, LessonStore

SECRET = b"\x00" * 32
_SYMPTOM = 'Error (2904): Declaration "TCfgParams" not found'


def _promoted_store(tmp_path: Path):
    s = LessonStore(tmp_path / "lessons", tmp_path / "knowledge", SECRET)
    c = LessonCandidate.create(
        trigger_signature=[_SYMPTOM], symptom=_SYMPTOM,
        fix="import ICooldownVault; reference ICooldownVault.TCfgParams",
        category="poc-compile")
    s.add(c)
    s.promote(c.sig_id)
    return s, c


def test_retrieve_returns_data_wrapped_block(tmp_path):
    s, _ = _promoted_store(tmp_path)
    blocks = s.retrieve("TCfgParams Declaration not found")
    assert blocks
    assert blocks[0].startswith("[DATA START]")
    assert blocks[0].endswith("[DATA END]")


def test_retrieve_empty_corpus_returns_nothing(tmp_path):
    s = LessonStore(tmp_path / "lessons", tmp_path / "knowledge", SECRET)
    assert s.retrieve("anything at all") == []


def test_append_lessons_inert_when_none_or_empty(tmp_path):
    prompt = "BASE PROMPT BODY"
    assert pqr._append_lessons(prompt, None, "ctx") == prompt          # no store
    s = LessonStore(tmp_path / "lessons", tmp_path / "knowledge", SECRET)
    assert pqr._append_lessons(prompt, s, "ctx") == prompt             # empty corpus (SC-007)


def test_append_lessons_adds_block_when_relevant(tmp_path):
    s, _ = _promoted_store(tmp_path)
    prompt = "BASE PROMPT BODY"
    out = pqr._append_lessons(prompt, s, "TCfgParams Declaration not found")
    assert out != prompt and out.startswith(prompt)  # additive, never mutates the base
    assert "[DATA START]" in out and "[DATA END]" in out


def test_retrieve_uses_lexical_fallback_without_embedder(tmp_path):
    s, _ = _promoted_store(tmp_path)
    assert s._kb.embedder is None            # no embedding backend
    assert s.retrieve("TCfgParams not found")  # still works (SC-006)

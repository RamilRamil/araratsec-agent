"""Spec 021 US1: session-create by repo URL — clone → external workspace; one-of.

The clone is mocked (no network). Asserts the URL flow binds the session to a
workspace outside the agent repo, and path/URL are mutually exclusive.
"""
from __future__ import annotations

import os

os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

import pytest

import frontend.backend.sessions as sessions
from frontend.backend.clone import CloneError
from frontend.backend.sessions import _AGENT_ROOT, SessionManager
from sr_agent.memory.episodic import EpisodicMemory


@pytest.fixture
def mgr(tmp_path):
    return SessionManager(EpisodicMemory(memory_root=tmp_path / "mem", secret_key=bytes(range(32))))


def test_repo_url_binds_session_to_external_workspace(mgr, tmp_path, monkeypatch):
    workspace = tmp_path / "ws" / "clone"
    (workspace / "src").mkdir(parents=True)
    monkeypatch.setattr(sessions, "clone_repo", lambda url, root, token="": workspace)
    s = mgr.start(repo_url="https://github.com/org/repo.git")
    assert s.loop._audit_root == workspace.resolve()
    assert _AGENT_ROOT not in workspace.resolve().parents   # external to the agent repo


def test_both_path_and_url_rejected(mgr, tmp_path):
    with pytest.raises(ValueError):
        mgr.start(project_path=str(tmp_path), repo_url="https://github.com/org/repo.git")


def test_neither_rejected(mgr):
    with pytest.raises(ValueError):
        mgr.start()


def test_clone_failure_surfaces_clearly_no_session(mgr, monkeypatch):
    def boom(url, root, token=""):
        raise CloneError("authentication required or repository not accessible")
    monkeypatch.setattr(sessions, "clone_repo", boom)
    with pytest.raises(ValueError) as ei:
        mgr.start(repo_url="https://github.com/org/private.git")
    assert "authentication" in str(ei.value).lower()
    assert mgr._sessions == {}   # no half-created session

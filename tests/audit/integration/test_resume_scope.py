"""Resume restores the bound scope_root (SC-002 / SC-002a)."""
from __future__ import annotations

import os

import pytest
from sr_agent.models.chat import ChatSession
from sr_agent.orchestrator.scope import (
    ContentScopePolicy,
    ScopeVerificationError,
    bind_scope,
    restore_scope_root,
    verify_content_identity,
)

from audit_agent.methodology.include import AUDIT_INCLUDE
from audit_agent.session import Principal


def _session() -> ChatSession:
    return ChatSession(principal=Principal(user_id="u", platform="cli", project_id="p"))


def test_resume_from_other_cwd_keeps_scope(tmp_path, monkeypatch):
    target = tmp_path / "A"
    (target / "contracts").mkdir(parents=True)
    (target / "contracts" / "V.sol").write_text("contract V {}\n")
    session = _session()
    bind_scope(session, ContentScopePolicy(scope_root=target, include=AUDIT_INCLUDE))
    other = tmp_path / "cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    assert restore_scope_root(session) == target.resolve()
    assert str(restore_scope_root(session)) != str(other.resolve())
    verify_content_identity(session)


def test_digest_mismatch_fails_resume(tmp_path):
    target = tmp_path / "A"
    (target / "contracts").mkdir(parents=True)
    sol = target / "contracts" / "V.sol"
    sol.write_text("contract V {}\n")
    session = _session()
    bind_scope(session, ContentScopePolicy(scope_root=target, include=AUDIT_INCLUDE))
    sol.write_text("contract V { function f() public {} }\n")
    with pytest.raises(ScopeVerificationError):
        verify_content_identity(session)


def test_outside_include_does_not_break_resume(tmp_path):
    target = tmp_path / "A"
    (target / "contracts").mkdir(parents=True)
    (target / "script").mkdir()
    (target / "contracts" / "V.sol").write_text("contract V {}\n")
    (target / "script" / "Deploy.sol").write_text("contract Deploy {}\n")
    session = _session()
    bind_scope(session, ContentScopePolicy(scope_root=target, include=("contracts/**",)))
    (target / "script" / "Deploy.sol").write_text("contract Deploy { uint x; }\n")
    verify_content_identity(session)
    from sr_agent.orchestrator.scope import path_is_included

    assert not path_is_included("script/Deploy.sol", session.include)

"""Stage 2 relay-driven pipeline tests (T055 + RLY4).

Deterministic: drives the emit -> pause -> respond -> resume -> ingest cycle
without any LLM. Verifies resumability, idempotency, and provenance.
"""
import json
import pytest
from pathlib import Path

from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.session import AuditInput, AuditSession, Principal
from sr_agent.models.memory import SourceType
from sr_agent.orchestrator.relay import save_response
from audit_agent.planner.stage2 import run_stage2

SECRET = b"test-secret-key-32-bytes-exactly!"


@pytest.fixture
def session() -> AuditSession:
    pr = Principal(user_id="u", platform="cli", project_id="proj1")
    return AuditSession(principal=pr, audit_input=AuditInput(path=Path("contracts"), principal=pr))


@pytest.fixture
def memory(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "mem", SECRET)


@pytest.fixture
def relay_dir(tmp_path: Path) -> Path:
    return tmp_path / "relay"


def _context(target: str) -> str:
    return f"// source for {target}"


def _finding_response(finding_id: str, severity: str = "high") -> str:
    return json.dumps({"findings": [{
        "finding_id": finding_id,
        "location": "Vault.sol:18",
        "function_name": "withdraw",
        "severity": severity,
        "bastet_tag": "reentrancy",
        "notes": "external call before state update",
    }]})


def _manifest(relay_dir: Path, session_id: str) -> dict:
    return json.loads((relay_dir / "manifest" / f"{session_id}.json").read_text())


def test_emits_requests_and_pauses(session, memory, relay_dir):
    result = run_stage2(session, ["Vault.sol", "Token.sol"], relay_dir, _context)
    assert result.status == "paused"
    assert result.requested == 2
    assert len(result.pending) == 2
    assert result.findings == []


def test_resume_ingests_after_responses(session, memory, relay_dir):
    # 1. emit + pause
    run_stage2(session, ["Vault.sol", "Token.sol"], relay_dir, _context)
    # 2. human answers both
    manifest = _manifest(relay_dir, session.session_id)
    for i, (rid, entry) in enumerate(manifest.items()):
        save_response(rid, relay_dir, _finding_response(f"H-{i}"))
    # 3. resume
    result = run_stage2(session, ["Vault.sol", "Token.sol"], relay_dir, _context)
    assert result.status == "done"
    assert result.ingested == 2
    assert len(result.findings) == 2
    assert [f.finding_id for f in result.findings]


def test_resume_is_idempotent(session, memory, relay_dir):
    run_stage2(session, ["Vault.sol"], relay_dir, _context)
    manifest = _manifest(relay_dir, session.session_id)
    rid = next(iter(manifest))
    save_response(rid, relay_dir, _finding_response("H-1"))

    first = run_stage2(session, ["Vault.sol"], relay_dir, _context)
    assert first.done and first.ingested == 1

    # calling again must not re-request or re-write
    again = run_stage2(session, ["Vault.sol"], relay_dir, _context)
    assert again.done
    assert again.requested == 0
    assert again.ingested == 0
    assert again.findings == []


def test_partial_response_stays_paused(session, memory, relay_dir):
    run_stage2(session, ["Vault.sol", "Token.sol"], relay_dir, _context)
    manifest = _manifest(relay_dir, session.session_id)
    rid_first = next(iter(manifest))
    save_response(rid_first, relay_dir, _finding_response("H-1"))

    result = run_stage2(session, ["Vault.sol", "Token.sol"], relay_dir, _context)
    assert result.status == "paused"
    assert result.ingested == 1
    assert len(result.pending) == 1


def test_malformed_response_stays_pending(session, memory, relay_dir):
    run_stage2(session, ["Vault.sol"], relay_dir, _context)
    manifest = _manifest(relay_dir, session.session_id)
    rid = next(iter(manifest))
    save_response(rid, relay_dir, "no json here, just prose")

    result = run_stage2(session, ["Vault.sol"], relay_dir, _context)
    assert result.status == "paused"
    assert rid in result.pending
    assert result.findings == []

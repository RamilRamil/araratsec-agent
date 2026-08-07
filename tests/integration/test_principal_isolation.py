"""Principal isolation tests (US3, FR-012, FR-013, SC-005).

Memory is scoped by principal.project_id. An injection into Principal A's
memory must never reach Principal B's audit context — enforced deterministically
at the directory level, before any HMAC check.
"""
import pytest
from pathlib import Path

from sr_agent.memory.episodic import EpisodicMemory, PrincipalMismatch
from audit_agent.session import Principal
from sr_agent.models.memory import MemoryRecord, SourceType

SECRET = b"test-secret-key-32-bytes-exactly!"


def _principal(project_id: str, user_id: str = "user") -> Principal:
    return Principal(user_id=user_id, platform="cli", project_id=project_id)


def _finding_record(project_id: str, finding_id: str) -> MemoryRecord:
    return MemoryRecord(
        project_id=project_id,
        target="Vault.sol",
        source_type=SourceType.tool_output,
        tool="run_slither",
        session_id="sess",
        finding={
            "finding_id": finding_id,
            "severity": "high",
            "location": "Vault.sol:10",
            "function_name": "withdraw",
        },
    )


@pytest.fixture
def memory(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path, SECRET)


def test_injection_in_A_does_not_affect_B(memory):
    """A malicious record in Principal A's memory never appears for Principal B."""
    a = _principal("project-A")
    b = _principal("project-B")

    # Attacker-controlled content lands in A's memory
    memory.write(_finding_record("project-A", "A-EVIL"), principal=a)
    # B has its own legitimate record
    memory.write(_finding_record("project-B", "B-001"), principal=b)

    b_records = memory.load_for_principal(b)

    assert all(r.project_id == "project-B" for r in b_records)
    assert "A-EVIL" not in {r.finding["finding_id"] for r in b_records}


def test_B_memory_only_returns_B_records(memory):
    """load_for_principal returns only the principal's own records."""
    a = _principal("project-A")
    b = _principal("project-B")

    memory.write(_finding_record("project-A", "A-001"), principal=a)
    memory.write(_finding_record("project-B", "B-001"), principal=b)
    memory.write(_finding_record("project-B", "B-002"), principal=b)

    b_records = memory.load_for_principal(b)
    finding_ids = {r.finding["finding_id"] for r in b_records}

    assert finding_ids == {"B-001", "B-002"}
    assert all(r.project_id == "project-B" for r in b_records)


def test_cross_principal_write_rejected(memory):
    """Writing a record whose project_id differs from the active principal raises."""
    b = _principal("project-B")
    with pytest.raises(PrincipalMismatch):
        memory.write(_finding_record("project-A", "A-001"), principal=b)


def test_cross_principal_load_rejected(memory):
    """Loading another principal's project_id raises rather than returning data."""
    b = _principal("project-B")
    with pytest.raises(PrincipalMismatch):
        memory.load("project-A", "Vault.sol", principal=b)


def test_load_for_principal_empty_when_no_memory(memory):
    """A principal with no memory directory loads cleanly as empty."""
    b = _principal("fresh-project")
    assert memory.load_for_principal(b) == []

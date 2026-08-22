"""Full audit acceptance test on the bundled vulnerable contract."""
from pathlib import Path

import pytest

from sr_agent.memory.episodic import EpisodicMemory
from sr_agent.orchestrator.relay import save_response

from audit_agent.pipeline import resume_audit, start_audit
from audit_agent.session import AuditInput, Principal

SECRET = b"test-secret-key-32-bytes-exactly!"


@pytest.fixture
def target_root(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[2] / "examples" / "vulnerable-vault" / "Vault.sol"
    dest = tmp_path / "target" / "contracts"
    dest.mkdir(parents=True)
    (dest / "Vault.sol").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest.parent


def _audit_input(root: Path) -> AuditInput:
    pr = Principal(user_id="auditor", platform="cli", project_id="vulnerable-vault")
    return AuditInput(path=root, principal=pr)


def test_audit_on_example_contract(tmp_path, target_root):
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"
    out = tmp_path / "audit-report.md"

    started = start_audit(
        _audit_input(target_root), target_root, mem, relay, runs,
        output=str(out), run_static=False,
    )
    assert started.status == "paused"
    assert started.pending >= 1

    request_files = sorted((relay / "requests").glob("*.md"))
    assert request_files
    packet = request_files[0].read_text()
    assert "function withdraw" in packet or "Vault.sol" in packet

    for path in request_files:
        save_response(path.stem, relay, (
            '{"findings": [{"finding_id": "HIGH-001",'
            ' "location": "contracts/Vault.sol:withdraw",'
            ' "function_name": "withdraw", "severity": "high",'
            ' "bastet_tag": "reentrancy",'
            ' "notes": "External call precedes the balance update."}]}'
        ))

    done = resume_audit(started.session_id, mem, relay, runs)
    assert done.status == "done"
    assert out.exists()
    report = out.read_text()
    assert "# Security Audit" in report


def test_audit_with_no_findings_still_reports(tmp_path, target_root):
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"
    out = tmp_path / "r.md"

    started = start_audit(
        _audit_input(target_root), target_root, mem, relay, runs,
        output=str(out), run_static=False,
    )
    for path in (relay / "requests").glob("*.md"):
        save_response(path.stem, relay, '{"findings": []}')

    done = resume_audit(started.session_id, mem, relay, runs)
    assert done.status == "done"
    assert out.exists()

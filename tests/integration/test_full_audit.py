"""Full audit acceptance test (T065).

Runs the whole relay pipeline on the bundled vulnerable contract and asserts the
end-to-end acceptance criteria: a HIGH finding is produced, the analysis request
wrapped the contract as data, findings are stored with external_llm_output
provenance, and the report carries Findings + Coverage.
"""
import json
import shutil
import subprocess

import pytest
from pathlib import Path

from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.session import AuditInput, Principal
from sr_agent.models.memory import SourceType
from audit_agent.pipeline import resume_audit, start_audit
from sr_agent.orchestrator.relay import save_response

SECRET = b"test-secret-key-32-bytes-exactly!"


def _slither_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(["docker", "image", "inspect", "slither-sandbox"],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


@pytest.fixture
def example_root() -> Path:
    return Path(__file__).resolve().parents[2] / "examples" / "vulnerable-vault"


def _audit_input(example_root: Path) -> AuditInput:
    pr = Principal(user_id="auditor", platform="cli", project_id="vulnerable-vault")
    return AuditInput(path=example_root, principal=pr)


def test_audit_on_example_contract(tmp_path, example_root):
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"
    out = tmp_path / "audit-report.md"

    # 1. start: Stage 1 prioritizes withdraw and emits a relay request, then pauses.
    started = start_audit(_audit_input(example_root), example_root, mem, relay, runs, output=str(out), run_static=False)
    assert started.status == "paused"
    assert started.pending >= 1

    # 2. the request packet wraps the contract source as DATA (not instructions).
    manifest = json.loads((relay / "manifest" / f"{started.session_id}.json").read_text())
    request_files = sorted((relay / "requests").glob("*.md"))
    packet = request_files[0].read_text()
    assert "[DATA START" in packet and "[DATA END]" in packet
    assert "function withdraw" in packet

    # 3. the human relays Claude's analysis (a real HIGH reentrancy finding).
    for rid, entry in manifest.items():
        fn = entry["target"].split(":")[-1]
        save_response(rid, relay, json.dumps({"findings": [{
            "finding_id": "HIGH-001",
            "location": entry["target"],
            "function_name": fn,
            "severity": "high",
            "bastet_tag": "reentrancy",
            "notes": "External call precedes the balance update — reentrancy drain.",
        }]}))

    # 4. resume: ingest, synthesize, write the report.
    done = resume_audit(started.session_id, mem, relay, runs)
    assert done.status == "done"
    assert done.findings_count >= 1

    # 5a. finding stored with relayed provenance (not human authority).
    records = mem.load_for_principal(_audit_input(example_root).principal)
    assert records and all(r.source_type is SourceType.external_llm_output for r in records)

    # 5b. report carries a HIGH finding, Findings and Coverage sections.
    report = out.read_text()
    assert "## Findings" in report
    assert "## Coverage" in report
    assert "[HIGH]" in report
    assert "withdraw" in report
    assert "Vault.sol:withdraw" in report          # analyzed
    assert "Vault.sol:deposit" in report           # not-analyzed coverage


def test_audit_with_no_findings_still_reports(tmp_path, example_root):
    """Even with an empty analysis, resume completes and writes a report."""
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"
    out = tmp_path / "r.md"

    started = start_audit(_audit_input(example_root), example_root, mem, relay, runs, output=str(out), run_static=False)
    manifest = json.loads((relay / "manifest" / f"{started.session_id}.json").read_text())
    for rid in manifest:
        save_response(rid, relay, json.dumps({"findings": []}))

    done = resume_audit(started.session_id, mem, relay, runs)
    assert done.status == "done"
    assert done.findings_count == 0
    assert "_No confirmed findings._" in out.read_text()


@pytest.mark.skipif(not _slither_ready(), reason="slither-sandbox image unavailable")
def test_static_pass_adds_tool_output_findings(tmp_path, example_root):
    """With Slither available, start_audit seeds tool_output findings itself."""
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"

    start_audit(_audit_input(example_root), example_root, mem, relay, runs,
                output=str(tmp_path / "r.md"), run_static=True)

    records = mem.load_for_principal(_audit_input(example_root).principal)
    slither_records = [
        r for r in records
        if r.source_type is SourceType.tool_output and r.tool == "run_slither"
    ]
    assert slither_records, "no Slither tool_output findings were written"
    assert any((r.finding or {}).get("bastet_tag") == "reentrancy" for r in slither_records)

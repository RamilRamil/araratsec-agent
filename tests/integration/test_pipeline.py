"""End-to-end audit pipeline tests (T063/T064, relay variant).

Drives start_audit -> pause -> respond -> resume_audit -> report, with no LLM.
"""
import json
import pytest
from pathlib import Path

from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.session import AuditInput, Principal
from audit_agent.pipeline import resume_audit, start_audit
from sr_agent.orchestrator.relay import save_response

SECRET = b"test-secret-key-32-bytes-exactly!"


@pytest.fixture
def example_root() -> Path:
    return Path(__file__).resolve().parents[2] / "examples" / "vulnerable-vault"


def _audit_input(example_root: Path) -> AuditInput:
    pr = Principal(user_id="u", platform="cli", project_id="vault")
    return AuditInput(path=example_root, principal=pr)


def _respond_all(relay_dir: Path, session_id: str) -> None:
    manifest = json.loads((relay_dir / "manifest" / f"{session_id}.json").read_text())
    for rid, entry in manifest.items():
        save_response(rid, relay_dir, json.dumps({"findings": [{
            "finding_id": "HIGH-001", "location": "Vault.sol:18",
            "function_name": "withdraw", "severity": "high",
            "bastet_tag": "reentrancy",
            "notes": "external call before state update",
        }]}))


def test_start_audit_pauses(tmp_path, example_root):
    res = start_audit(
        _audit_input(example_root), example_root,
        EpisodicMemory(tmp_path / "mem", SECRET),
        tmp_path / "relay", tmp_path / "runs", output=str(tmp_path / "r.md"),
        run_static=False,
    )
    assert res.status == "paused"
    assert res.pending >= 1
    assert (tmp_path / "runs" / f"{res.session_id}.json").exists()


def test_full_audit_then_resume(tmp_path, example_root):
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"
    out = tmp_path / "report.md"

    res = start_audit(_audit_input(example_root), example_root, mem, relay, runs,
                      output=str(out), run_static=False)
    _respond_all(relay, res.session_id)
    res2 = resume_audit(res.session_id, mem, relay, runs)

    assert res2.status == "done"
    assert res2.findings_count >= 1
    assert out.exists()
    text = out.read_text()
    assert "# Security Audit" in text
    assert "withdraw" in text


def test_resume_unknown_session_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resume_audit("nope", EpisodicMemory(tmp_path / "m", SECRET),
                     tmp_path / "relay", tmp_path / "runs")


def test_progress_emitted_during_audit(tmp_path, example_root):
    import io
    from sr_agent.io.progress import ProgressStream

    buf = io.StringIO()
    start_audit(
        _audit_input(example_root), example_root,
        EpisodicMemory(tmp_path / "mem", SECRET),
        tmp_path / "relay", tmp_path / "runs",
        output=str(tmp_path / "r.md"), progress=ProgressStream(stream=buf),
        run_static=False,
    )
    out = buf.getvalue()
    assert "Stage 1 complete" in out
    assert "Paused" in out


def test_resume_still_pending_without_responses(tmp_path, example_root):
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"
    res = start_audit(_audit_input(example_root), example_root, mem, relay, runs,
                      output=str(tmp_path / "r.md"), run_static=False)
    res2 = resume_audit(res.session_id, mem, relay, runs)
    assert res2.status == "paused"

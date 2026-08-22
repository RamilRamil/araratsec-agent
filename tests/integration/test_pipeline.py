"""End-to-end audit pipeline tests against the KernelActionExecutor path."""
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
    pr = Principal(user_id="u", platform="cli", project_id="vault")
    return AuditInput(path=root, principal=pr)


def _respond_requests(relay_dir: Path) -> None:
    for path in sorted((relay_dir / "requests").glob("*.md")):
        save_response(
            path.stem,
            relay_dir,
            '{"findings": [{"finding_id": "HIGH-001", "location": "contracts/Vault.sol:18",'
            ' "function_name": "withdraw", "severity": "high", "bastet_tag": "reentrancy",'
            ' "notes": "external call before state update"}]}',
        )


def test_start_audit_pauses(tmp_path, target_root):
    res = start_audit(
        _audit_input(target_root), target_root,
        EpisodicMemory(tmp_path / "mem", SECRET),
        tmp_path / "relay", tmp_path / "runs", output=str(tmp_path / "r.md"),
        run_static=False,
    )
    assert res.status == "paused"
    assert res.pending >= 1
    assert (tmp_path / "runs" / f"{res.session_id}.json").exists()


def test_full_audit_then_resume(tmp_path, target_root):
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"
    out = tmp_path / "report.md"

    res = start_audit(_audit_input(target_root), target_root, mem, relay, runs,
                      output=str(out), run_static=False)
    _respond_requests(relay)
    res2 = resume_audit(res.session_id, mem, relay, runs)

    assert res2.status == "done"
    assert out.exists()
    text = out.read_text()
    assert "# Security Audit" in text


def test_resume_unknown_session_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resume_audit("nope", EpisodicMemory(tmp_path / "m", SECRET),
                     tmp_path / "relay", tmp_path / "runs")


def test_progress_emitted_during_audit(tmp_path, target_root):
    import io

    from sr_agent.io.progress import ProgressStream

    buf = io.StringIO()
    start_audit(
        _audit_input(target_root), target_root,
        EpisodicMemory(tmp_path / "mem", SECRET),
        tmp_path / "relay", tmp_path / "runs",
        output=str(tmp_path / "r.md"), progress=ProgressStream(stream=buf),
        run_static=False,
    )
    out = buf.getvalue()
    assert "Stage 1" in out or "stage=" in out


def test_resume_still_pending_without_responses(tmp_path, target_root):
    mem = EpisodicMemory(tmp_path / "mem", SECRET)
    relay, runs = tmp_path / "relay", tmp_path / "runs"
    res = start_audit(_audit_input(target_root), target_root, mem, relay, runs,
                      output=str(tmp_path / "r.md"), run_static=False)
    res2 = resume_audit(res.session_id, mem, relay, runs)
    assert res2.status == "paused"

"""Live Slither integration (T050).

Runs real Slither in the sandbox. Auto-skips if Docker or the slither-sandbox
image is unavailable, so the suite stays green without them.
"""
import shutil
import subprocess

import pytest
from pathlib import Path

from sr_agent.tools.sandbox import DockerSandbox
from audit_agent.tools.static_analysis import run_slither


def _slither_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", "slither-sandbox"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _slither_ready(), reason="Docker or slither-sandbox image unavailable"
)


def test_slither_detects_reentrancy_on_example():
    root = Path(__file__).resolve().parents[2] / "examples" / "vulnerable-vault"
    findings = run_slither(root / "Vault.sol", root, DockerSandbox())
    checks = {f.check for f in findings}
    assert any("reentrancy" in c for c in checks), f"no reentrancy in {checks}"
    assert any(f.severity == "high" for f in findings)

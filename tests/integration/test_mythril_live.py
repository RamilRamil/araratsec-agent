"""Live Mythril integration (T051).

Real symbolic execution — slow. Auto-skips if Docker or the mythril-sandbox
image is unavailable so the suite stays green without them.
"""
import shutil
import subprocess

import pytest
from pathlib import Path

from sr_agent.tools.sandbox import DockerSandbox
from audit_agent.tools.static_analysis import run_mythril


def _mythril_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", "mythril-sandbox"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mythril_ready(), reason="Docker or mythril-sandbox image unavailable"
)


@pytest.mark.slow
def test_mythril_flags_external_call_on_example():
    root = Path(__file__).resolve().parents[2] / "examples" / "vulnerable-vault"
    findings = run_mythril(root / "Vault.sol", root, DockerSandbox(), timeout_s=300)
    # The withdraw() external call should surface at least one issue.
    assert findings, "mythril returned no issues on a known-vulnerable contract"
    swc_ids = {f.swc_id for f in findings}
    assert any(swc for swc in swc_ids), f"no SWC ids in {swc_ids}"

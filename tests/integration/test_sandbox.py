"""DockerSandbox integration tests (US4, T042).

Real Docker. Skipped automatically if the daemon or the alpine:latest image
is unavailable, so the suite stays green in environments without Docker.
"""
import shutil
import subprocess

import pytest

from sr_agent.tools.sandbox import DockerSandbox, Mount, SandboxTimeout


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", "alpine:latest"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_ready(),
    reason="Docker daemon or alpine:latest image unavailable",
)


@pytest.fixture
def sandbox() -> DockerSandbox:
    return DockerSandbox()


def test_basic_exec(sandbox):
    r = sandbox.run("alpine:latest", ["echo", "hi"])
    assert r.ok
    assert "hi" in r.stdout


def test_exit_code_propagates(sandbox):
    r = sandbox.run("alpine:latest", ["sh", "-c", "exit 7"])
    assert r.exit_code == 7
    assert not r.ok


def test_network_is_isolated(sandbox):
    # --network none means the egress attempt fails and the fallback prints.
    r = sandbox.run(
        "alpine:latest",
        ["sh", "-c", "wget -T2 -q -O- http://example.com || echo NO_NETWORK"],
    )
    assert "NO_NETWORK" in r.stdout


def test_timeout_raises(sandbox):
    with pytest.raises(SandboxTimeout):
        sandbox.run("alpine:latest", ["sleep", "10"], timeout_s=1.5)


def test_readonly_mount_blocks_write(sandbox, tmp_path):
    (tmp_path / "src.txt").write_text("original")
    mount = Mount(host_path=tmp_path, container_path="/src", read_only=True)
    r = sandbox.run(
        "alpine:latest",
        ["sh", "-c", "echo x > /src/new.txt || echo WRITE_BLOCKED"],
        mounts=[mount],
    )
    assert "WRITE_BLOCKED" in r.stdout
    assert not (tmp_path / "new.txt").exists()

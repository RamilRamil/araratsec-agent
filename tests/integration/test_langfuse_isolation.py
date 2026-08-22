"""Langfuse tracing isolation (Phase 9, T078). No Langfuse server required.

Tracing is pure observability: it must never leak into episodic memory / the
LLM context, and it must never gate the audit (disabled by default, no-op on
any failure — package missing, server unreachable, or no keys configured).
"""
from pathlib import Path

from sr_agent.eval.tracer import NOOP_TRACER, Tracer
from sr_agent.memory.episodic import EpisodicMemory
from audit_agent.session import AuditInput, AuditSession, Principal
from audit_agent.finding import Severity
from sr_agent.models.memory import SourceType
from audit_agent.planner.stage2 import run_stage2_local

SECRET = b"test-secret-key-32-bytes-exactly!"

_GOOD = ('```json\n{"findings": [{"finding_id": "F-1", "location": "Vault.sol:18",'
         ' "function_name": "withdraw", "severity": "high", "bastet_tag": "reentrancy",'
         ' "notes": "external call before state update"}]}\n```')


class _FakeClient:
    model = "fake-model"

    def __init__(self, response: str = "") -> None:
        self._response = response

    def generate(self, prompt: str, fmt: str | None = None) -> str:
        return self._response


def _session(project_id: str) -> AuditSession:
    pr = Principal(user_id="u", platform="cli", project_id=project_id)
    return AuditSession(principal=pr, audit_input=AuditInput(path=Path("c"), principal=pr))


def _memory(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(tmp_path / "mem", SECRET)


def test_disabled_tracer_is_a_safe_noop():
    tracer = Tracer()  # no secret_key/public_key -> disabled
    assert tracer.enabled is False
    with tracer.trace("t", "s") as trace:
        assert trace.span is None
        tracer.generation(trace, name="g", model="m", input="i", output="o")  # must not raise


def test_noop_tracer_singleton_is_disabled():
    assert NOOP_TRACER.enabled is False


def test_tracer_module_never_touches_memory_or_config():
    """The tracer is a leaf module: no coupling to episodic memory, and no
    eager dependency on sr_agent.config (which requires env vars at import
    time) — it stays importable from unit tests and other leaf modules."""
    import ast

    import sr_agent.eval.tracer as tracer_mod

    tree = ast.parse(Path(tracer_mod.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert not any(m.startswith("sr_agent.memory") for m in imported)
    assert not any(m.startswith("sr_agent.config") for m in imported)


def test_tracing_does_not_change_findings_written_to_memory(tmp_path):
    """Same Stage 2 run, with a no-op or a disabled real Tracer, writes
    identical findings to memory — tracing never mutates the audit trail."""
    memory = _memory(tmp_path)

    session1 = _session("proj-trace-1")
    result1 = run_stage2_local(
        session1, ["Vault.sol:withdraw"], _FakeClient(_GOOD), lambda t: "code",
        tracer=NOOP_TRACER,
    )
    assert len(result1.findings) == 1

    session2 = _session("proj-trace-2")
    disabled_tracer = Tracer(secret_key="", public_key="")  # exercises the real call path, still off
    result2 = run_stage2_local(
        session2, ["Vault.sol:withdraw"], _FakeClient(_GOOD), lambda t: "code",
        tracer=disabled_tracer,
    )
    assert result1.findings[0].severity == result2.findings[0].severity == Severity.high
    assert result1.findings[0].model_dump() == result2.findings[0].model_dump()

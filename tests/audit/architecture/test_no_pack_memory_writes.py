"""Package-wide empty write allowlist (FR-026 / SC-006)."""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3] / "audit_agent"
_CLI = _ROOT / "cli.py"


def _iter_prod_py() -> list[Path]:
    return [
        p for p in _ROOT.rglob("*.py")
        if "test_" not in p.name and "__pycache__" not in p.parts
    ]


def test_no_memory_record_or_write_in_production():
    offenders: list[str] = []
    for path in _iter_prod_py():
        source = path.read_text(encoding="utf-8")
        if "MemoryRecord(" in source:
            offenders.append(f"{path}: MemoryRecord(")
        if "memory.write(" in source:
            offenders.append(f"{path}: memory.write(")
    assert offenders == []


def test_episodic_memory_import_only_in_cli():
    offenders: list[str] = []
    for path in _iter_prod_py():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "sr_agent.memory.episodic":
                if any(alias.name == "EpisodicMemory" for alias in node.names):
                    if path.resolve() != _CLI.resolve():
                        offenders.append(str(path.relative_to(_ROOT.parent)))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith("episodic") or alias.name == "EpisodicMemory":
                        if path.resolve() != _CLI.resolve():
                            offenders.append(str(path.relative_to(_ROOT.parent)))
    assert offenders == []

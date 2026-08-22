"""pack/006 US3: capability has one home; pack does not import scripts."""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_PACK = _REPO / "audit_agent"
_SCRIPTS = _REPO / "scripts"

RELOCATED = (
    "patch_reconstruct.py",
    "scaffold_causes.py",
    "solidity_index.py",
    "scaffold_api_inventory.py",
    "scaffold_reachability.py",
    "compiled_checkpoint.py",
    "observed_fork_grounding.py",
    "anti_mock_grounding.py",
    "solidity_utils.py",
    "solidity_fixers.py",
)


def _prod_py(root: Path) -> list[Path]:
    return [
        p for p in root.rglob("*.py")
        if "test_" not in p.name and "__pycache__" not in p.parts
    ]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def test_relocated_basename_has_one_production_home() -> None:
    pack_names = {p.name for p in _prod_py(_PACK)}
    script_names = {p.name for p in _prod_py(_SCRIPTS)}
    dual = sorted(n for n in RELOCATED if n in pack_names and n in script_names)
    missing = sorted(n for n in RELOCATED if n not in pack_names)
    leftover = sorted(n for n in RELOCATED if n in script_names)
    assert missing == [], f"relocated module(s) missing from audit_agent/: {missing}"
    assert leftover == [], f"relocated module(s) still under scripts/: {leftover}"
    assert dual == []


def test_pack_does_not_import_scripts() -> None:
    offenders: list[str] = []
    for path in _prod_py(_PACK):
        for name in _imported_modules(path):
            if name == "scripts" or name.startswith("scripts."):
                offenders.append(f"{path.relative_to(_REPO)} imports {name}")
    assert offenders == []

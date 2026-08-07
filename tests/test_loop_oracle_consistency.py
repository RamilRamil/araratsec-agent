"""Feature 037 US3 (FR-004/FR-007) — loop↔oracle consistency.

Offline/deterministic/target-free. The loop TESTS an artifact each iteration and the oracle
JUDGES an artifact at the verdict; they MUST be byte-identical. The whole argument rests on the
deterministic fixer composition `fix = _seq_postmodel ∘ ensure_base_imports` being BYTE-IDEMPOTENT,
so the oracle's re-application of `_seq_postmodel` (poc_queue_runner ~2368) is a no-op on the code
the loop already fixed. See contracts/consistency.md.
"""
from pathlib import Path

from scripts import exploit_loop as el
from scripts.solidity_fixers import _seq_postmodel


class _Sym:
    def __init__(self, file, kind="contract"):
        self.file = file
        self.kind = kind


class _Index:
    """Minimal AST symbol index: resolves the base contract to its real file."""
    def __init__(self, base_name, base_file):
        self._name = base_name
        self._file = base_file

    def lookup(self, name):
        return [_Sym(self._file)] if name == self._name else []

    def nested_container(self, name):
        return None   # no name in this fixture is a nested type


def _fixup_setup(tmp_path):
    """A PoC that INHERITS a base without importing it — the canonical fixup case (loop-live rounding Low).
    Returns (code, fix) where fix = _seq_postmodel ∘ ensure_base_imports, wired exactly as the loop
    wire builds it (scaffold empty ⇒ guard False, matching a no-scaffold finding)."""
    project = tmp_path / "project"
    poc_dir = project / "test" / "PoC"
    base_file = project / "test" / "Base.sol"
    base_file.parent.mkdir(parents=True)
    base_file.write_text("// SPDX\npragma solidity ^0.8.0;\ncontract Base {}\n")
    poc_dir.mkdir(parents=True)
    code = ("// SPDX-License-Identifier: MIT\n"
            "pragma solidity ^0.8.0;\n"
            "contract PoC is Base { function test_x() public {} }\n")
    index = _Index("Base", base_file)

    def fix(c: str) -> str:
        c, _bi = el.ensure_base_imports(c, index, poc_dir)
        c, _applied = _seq_postmodel(c, project, index, "(none)", "", False)
        return c

    return code, fix


# ───────────────────── T018 (FR-004): byte-idempotency — the load-bearing invariant ─────────────────────

def test_fix_is_byte_idempotent(tmp_path):
    code, fix = _fixup_setup(tmp_path)
    once = fix(code)
    twice = fix(once)
    # the base import must actually have been injected (the fixup fired), else the test is vacuous
    assert "import" in once and "Base" in once
    # fix(fix(x)) == fix(x) BYTE-for-byte — a fixer that double-injects an import would FAIL here.
    assert twice == once


# ───────────────────── T019 (FR-004): the oracle's re-apply is a no-op ⇒ loop == oracle ─────────────────────

def test_oracle_reapply_of_seq_postmodel_is_noop_on_fixed_code(tmp_path):
    """The loop hands the oracle `fix(code)`; the oracle then re-applies `_seq_postmodel` alone
    (poc_queue_runner ~2368). On already-fixed code that re-apply MUST be byte-identical — this is
    exactly what makes the loop-tested artifact and the oracle-judged artifact the same bytes, so a
    loop 'triggered' can never coexist with an oracle 'compiled=False' on the same draft."""
    code, fix = _fixup_setup(tmp_path)
    loop_artifact = fix(code)                       # what the loop's _run_poc tested + handed off
    project = tmp_path / "project"
    index = _Index("Base", project / "test" / "Base.sol")
    # the oracle re-applies ONLY _seq_postmodel (it does not re-run ensure_base_imports):
    oracle_artifact, applied = _seq_postmodel(loop_artifact, project, index, "(none)", "", False)
    assert oracle_artifact == loop_artifact         # byte-identical: the re-apply changed nothing
    assert applied == []                             # and reported no fixer as applied


# ───────────────────── T020 (FR-007/SC-006): the verdict stays with the unchanged oracle ─────────────────────

def test_loop_and_fixers_never_set_passed_verified():
    """Neither the loop nor any fixer may set `passed_verified` — a triggering PoC's verified
    status comes SOLELY from the unchanged oracle (_poc_defects/fork/mutation_verify). The loop
    only ever emits a candidate + a `triggered` flag (FR-007)."""
    # structural: the loop module never ASSIGNS passed_verified (a prose mention in the module
    # docstring — "passed_verified stays with the unchanged oracle" — is fine; an assignment is not),
    # and LoopResult exposes only a `triggered` flag — no verified-style attribute.
    import re as _re
    _ASSIGN = _re.compile(r'passed_verified\s*=(?!=)|["\']passed_verified["\']\s*:')
    loop_src = Path(el.__file__).read_text()
    assert not _ASSIGN.search(loop_src), "loop module must not ASSIGN passed_verified (FR-007)"
    from scripts.solidity_fixers import __file__ as fx_file
    assert not _ASSIGN.search(Path(fx_file).read_text()), "fixers must not ASSIGN passed_verified"
    res = el.LoopResult("triggered", "code", el.LoopState(), 1)
    assert res.triggered is True
    assert not hasattr(res, "passed_verified")
    assert not hasattr(res, "verified")

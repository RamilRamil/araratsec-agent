"""Live-run fix (2026-07-14): force the PoC to inherit the test_scaffold's LEAF contract.

Given a working scaffold, the local model wrote a coherent, right-mechanism exploit but
inherited the imported grandparent (`IssuerDeploy`) instead of the leaf (`SpecTest`), losing
setUp + every deployed symbol → a cascade of `Undeclared identifier`. `_scaffold_base_name`
identifies the leaf; `_fix_scaffold_base` deterministically enforces it.
"""
from scripts.poc_queue_runner import _scaffold_base_name, read_scaffold
from audit_agent.proof.solidity_fixers import _fix_scaffold_base

_SCAFFOLD = (
    'import {IssuerDeploy} from "./IssuerDeploy.t.sol";\n'
    'contract SpecTest is IssuerDeploy {\n'
    '    CooldownVault public cooldownVault;\n'
    '    function setUp() public override { _deployCooldownVault(); }\n'
    '}\n'
)


def test_leaf_is_the_declared_contract_not_the_imported_parent():
    assert _scaffold_base_name(_SCAFFOLD) == "SpecTest"


def test_leaf_single_contract():
    assert _scaffold_base_name("contract Base { }") == "Base"


def test_leaf_none_when_no_contract():
    assert _scaffold_base_name("// just a comment") is None
    assert _scaffold_base_name("") is None


def test_leaf_ignores_the_word_contract_in_comments_and_strings():
    # 2026-07-14 bug: an assert message "CooldownVault contract should be configured" made
    # the loose regex return `should`, and the guard forced `is should` (Error 7920).
    txt = ('// the CooldownVault contract should be configured properly\n'
           'contract SpecTest is IssuerDeploy {\n'
           '    function setUp() public { require(true, "the contract should deploy"); }\n'
           '}\n')
    assert _scaffold_base_name(txt) == "SpecTest"


def test_leaf_ignores_header_prose_from_read_scaffold(tmp_path):
    # read_scaffold prepends a `// ... INHERIT the contract SpecTest ...` comment line;
    # _scaffold_base_name over that full block must still resolve the real leaf.
    p = tmp_path / "SpecTest.t.sol"
    p.write_text(_SCAFFOLD, encoding="utf-8")
    assert _scaffold_base_name(read_scaffold(tmp_path, [p])) == "SpecTest"


def test_leaf_picks_the_non_base_when_multiple_in_file():
    txt = "contract Parent { } contract Leaf is Parent { function setUp() public {} }"
    assert _scaffold_base_name(txt) == "Leaf"


def test_guard_rewrites_wrong_parent_base():
    poc = ('import {IssuerDeploy} from "../../test/issuer/SpecTest.t.sol";\n'
           'contract PoC_H_01 is IssuerDeploy {\n'
           '    function test_exploit() public { cooldownVault.balanceOf(x); }\n}')
    out, changed = _fix_scaffold_base(poc, _SCAFFOLD)
    assert changed
    assert "contract PoC_H_01 is SpecTest {" in out
    assert "is IssuerDeploy" not in out


def test_guard_noop_when_already_correct():
    poc = "contract PoC_H_01 is SpecTest {\n function test_x() public {}\n}"
    assert _fix_scaffold_base(poc, _SCAFFOLD) == (poc, False)


def test_guard_noop_without_scaffold():
    poc = "contract PoC is Test { function test_x() public {} }"
    assert _fix_scaffold_base(poc, "") == (poc, False)


def test_guard_replaces_full_base_list_with_leaf():
    poc = "contract PoC_H_01 is Test, IssuerDeploy {\n function test_x() public {}\n}"
    out, changed = _fix_scaffold_base(poc, _SCAFFOLD)
    assert changed and "contract PoC_H_01 is SpecTest {" in out


def test_guard_is_idempotent():
    poc = "contract PoC_H_01 is IssuerDeploy {\n function test_x() public {}\n}"
    out, _ = _fix_scaffold_base(poc, _SCAFFOLD)
    out2, changed2 = _fix_scaffold_base(out, _SCAFFOLD)
    assert changed2 is False and out2 == out


def test_read_scaffold_names_the_leaf_base(tmp_path):
    p = tmp_path / "SpecTest.t.sol"
    p.write_text(_SCAFFOLD, encoding="utf-8")
    rendered = read_scaffold(tmp_path, [p])
    assert "INHERIT the contract `SpecTest`" in rendered
    assert "is SpecTest" in rendered

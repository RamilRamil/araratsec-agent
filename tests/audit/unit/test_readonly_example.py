"""Audit example-contract content test (extracted from tests/unit/test_readonly.py, feature 048).

`search_code` is a kernel primitive (covered by kernel unit tests with synthetic fixtures).
THIS test asserts the real AUDIT `examples/vulnerable-vault` fixture has the expected
reentrancy shape — that example lives in Repo B, not the kernel carve, so it belongs here.
"""
from pathlib import Path

from sr_agent.tools.readonly import search_code


def test_example_vault_has_reentrancy_shape():
    example = Path(__file__).resolve().parents[3] / "examples" / "vulnerable-vault"
    hits = search_code("call{value:", example)
    assert any(h.file == "Vault.sol" for h in hits)

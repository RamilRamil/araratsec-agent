"""Pack-side TOOL_REGISTRY description hash check (feature 003, FR-012, D9).

CI-time integrity only: this is not a startup-integrity guarantee. The kernel
`verify_all_hashes()` still iterates only the kernel registry at runtime.
"""
from __future__ import annotations

from sr_agent.tools.registry import _hash

from audit_agent.tool_registry import TOOL_REGISTRY


def test_pack_registry_hashes_match_descriptions():
    for name, tool in TOOL_REGISTRY.items():
        computed = _hash(tool.description)
        assert computed == tool.description_hash, (
            f"TOOL_REGISTRY[{name!r}] description hash mismatch"
        )


def test_tampered_description_fails_hash_check():
    tool = next(iter(TOOL_REGISTRY.values()))
    assert _hash(tool.description + " tampered") != tool.description_hash

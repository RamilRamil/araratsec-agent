"""The audit pack's DOMAIN analyzer tool registry (feature 002, US1).

Relocated from the kernel `sr_agent/tools/registry.py`. Holds ONLY the domain
analyzer tools — one per `AuditActionType` id. The kernel-generic reads
(`read_file`, `search_code`, D6) and the machinery tools (`write_memory`,
`request_human_confirmation`, `escalate`) stay kernel-side and are inherited; the
dropped `run_auditor_skill` action has no tool here either.

Supplied to the kernel via `CapabilityPack.tools`. `ToolDefinition` / `_hash`
are IMPORTED from the kernel (the shared tool-integrity primitive), not copied.
"""
from __future__ import annotations

from sr_agent.tools.registry import ToolDefinition, _hash

_D_BUILD_GRAPH = (
    "Build a call graph and data-flow graph for the audit scope. "
    "Returns a structured JSON graph. Used by Stage 1 for SIG construction."
)

_D_RUN_SLITHER = (
    "Run Slither static analyser on a target file or directory inside a sandboxed Docker container. "
    "Detectors must be selected from the SlitherDetector enum — no arbitrary detector strings. "
    "Returns structured JSON findings."
)

_D_RUN_MYTHRIL = (
    "Run Mythril symbolic execution on a target contract inside a sandboxed Docker container. "
    "Returns structured JSON findings. May take up to 5 minutes per contract."
)

_D_ANALYZE_TRANSACTIONS = (
    "Fetch and analyse on-chain transactions for a contract address via Alchemy archive node. "
    "Limit: 10000 blocks per call. Returns structured summary of suspicious patterns."
)

_D_DECOMPILE_BYTECODE = (
    "Decompile EVM bytecode for a given contract address using a local decompiler. "
    "Used when source code is unavailable. Returns decompiled pseudo-Solidity."
)

_D_WRITE_POC = (
    "Write a Proof-of-Concept exploit test in Solidity to tests/poc/. "
    "Requires prior human out-of-band confirmation. Deploys only to local Anvil."
)

_D_RUN_TESTS = (
    "Run Foundry test suite (forge test) for a specific test file inside a sandboxed container. "
    "Requires prior human out-of-band confirmation."
)

_D_DEPLOY_TEST_CONTRACT = (
    "Deploy a contract to local Anvil testnet only. "
    "Cannot deploy to mainnet or any live network. Requires human out-of-band confirmation."
)


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    t.name: t for t in [
        ToolDefinition("build_graph",          _D_BUILD_GRAPH,          "read_only",     _hash(_D_BUILD_GRAPH)),
        ToolDefinition("run_slither",          _D_RUN_SLITHER,          "read_only",     _hash(_D_RUN_SLITHER)),
        ToolDefinition("run_mythril",          _D_RUN_MYTHRIL,          "read_only",     _hash(_D_RUN_MYTHRIL)),
        ToolDefinition("analyze_transactions", _D_ANALYZE_TRANSACTIONS, "read_only",     _hash(_D_ANALYZE_TRANSACTIONS)),
        ToolDefinition("decompile_bytecode",   _D_DECOMPILE_BYTECODE,   "read_only",     _hash(_D_DECOMPILE_BYTECODE)),
        ToolDefinition("write_poc",            _D_WRITE_POC,            "write_execute", _hash(_D_WRITE_POC)),
        ToolDefinition("run_tests",            _D_RUN_TESTS,            "write_execute", _hash(_D_RUN_TESTS)),
        ToolDefinition("deploy_test_contract", _D_DEPLOY_TEST_CONTRACT, "write_execute", _hash(_D_DEPLOY_TEST_CONTRACT)),
    ]
}

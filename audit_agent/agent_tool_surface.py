"""Executable agent-tool surface (feature 003).

Maps every pack domain id plus the kernel-generic reads onto one `SurfaceEntry`
holding a real executor callable (or None when unavailable). Dispatch is a
lookup into this mapping - never a second `if` chain of analyzer ids (D2).

`offered` is the chat vocabulary; `available` is "has an executable route".
`offered=true` implies `available=true` (FR-001). Write-execute ids stay
`offered=false`; their in-turn path is the kernel confirmation gate, and only
`execute_confirmed` runs `write_poc` / `run_tests`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from sr_agent.tools.readonly import ReadOnlyToolError, read_file, search_code
from sr_agent.tools.sandbox import SandboxError, SandboxTimeout

from audit_agent.actions import AuditActionType
from audit_agent.config import config
from audit_agent.tools.onchain import (
    OnChainError,
    analyze_transactions,
    make_alchemy_fetcher,
)
from audit_agent.tools.static_analysis import (
    MythrilError,
    SlitherError,
    run_mythril,
    run_slither,
)

if TYPE_CHECKING:
    from sr_agent.models.action import Action
    from sr_agent.orchestrator.pack import PackContext

Executor = Callable[["Action", "PackContext"], str]

# Pack-owned render budget (FR-009). PackContext exposes no context window.
MAX_RESULT_ITEMS = 32
MAX_RESULT_BYTES = 8192


@dataclass(frozen=True)
class SurfaceEntry:
    required_params: tuple[str, ...]
    executor: Executor | None
    offered: bool
    available: bool
    missing_precondition: str
    valid_params: dict
    summary: str


@dataclass(frozen=True)
class ToolResultPayload:
    """Structured tool outcome rendered inside the DATA wrapper (D5)."""
    status: str
    tool: str
    cause: str = ""
    retryable: bool = False
    shown: int | None = None
    total: int | None = None
    omitted: int | None = None
    body: str = ""


def truncate_lines(lines: list[str]) -> tuple[list[str], int, int, int]:
    """Bound rendered items by count and bytes. Returns (kept, shown, total, omitted)."""
    total = len(lines)
    kept: list[str] = []
    nbytes = 0
    for line in lines:
        if len(kept) >= MAX_RESULT_ITEMS:
            break
        encoded = line.encode("utf-8")
        extra = len(encoded) + (1 if kept else 0)
        if kept and nbytes + extra > MAX_RESULT_BYTES:
            break
        if not kept and extra > MAX_RESULT_BYTES:
            cut = MAX_RESULT_BYTES
            kept.append(encoded[:cut].decode("utf-8", errors="ignore"))
            nbytes = cut
            break
        kept.append(line)
        nbytes += extra
    return kept, len(kept), total, total - len(kept)


def render_tool_result(
    payload: ToolResultPayload, ctx: "PackContext", path: str = "",
) -> str:
    parts = [
        f"status={payload.status}",
        f"tool={payload.tool}",
        f"retryable={payload.retryable}",
    ]
    if payload.cause:
        parts.append(f"cause={payload.cause}")
    if payload.shown is not None:
        parts.append(f"shown={payload.shown}")
        parts.append(f"total={payload.total}")
        parts.append(f"omitted={payload.omitted}")
    header = " ".join(parts)
    content = f"{header}\n{payload.body}" if payload.body else header
    return ctx.wrap_data(content, tool=payload.tool, path=path)


def unavailable_payload(
    tool: str, cause: str, ctx: "PackContext", path: str = "",
) -> str:
    return render_tool_result(
        ToolResultPayload(
            status="unavailable", tool=tool, cause=cause, retryable=False,
        ),
        ctx, path,
    )


def _payload_from_error(exc: BaseException, tool: str, ctx: "PackContext", path: str) -> str:
    if isinstance(exc, SandboxTimeout):
        return render_tool_result(
            ToolResultPayload(
                status="timeout", tool=tool, cause=str(exc), retryable=True,
            ),
            ctx, path,
        )
    return render_tool_result(
        ToolResultPayload(
            status="did_not_run", tool=tool, cause=str(exc), retryable=True,
        ),
        ctx, path,
    )


def _ran_payload(tool: str, lines: list[str], ctx: "PackContext", path: str) -> str:
    kept, shown, total, omitted = truncate_lines(lines)
    return render_tool_result(
        ToolResultPayload(
            status="ran", tool=tool, retryable=False,
            shown=shown, total=total, omitted=omitted,
            body="\n".join(kept),
        ),
        ctx, path,
    )


def _exec_read_file(action: "Action", ctx: "PackContext") -> str:
    params = action.params
    try:
        content = read_file(params["path"], ctx.scope_root)
        return ctx.wrap_data(content, tool="read_file", path=str(params.get("path", "")))
    except ReadOnlyToolError as e:
        return ctx.wrap_data(f"TOOL ERROR: {e}", tool="read_file", path="")
    except KeyError as e:
        return ctx.wrap_data(f"TOOL ERROR: missing required param {e}", tool="read_file", path="")


def _exec_search_code(action: "Action", ctx: "PackContext") -> str:
    params = action.params
    try:
        root = params.get("root", str(ctx.scope_root))
        hits = search_code(params["pattern"], root, file_ext=".sol")
        body = "\n".join(f"{h.file}:{h.line}: {h.text}" for h in hits) or "(no matches)"
        return ctx.wrap_data(body, tool="search_code", path=str(root))
    except ReadOnlyToolError as e:
        return ctx.wrap_data(f"TOOL ERROR: {e}", tool="search_code", path="")
    except KeyError as e:
        return ctx.wrap_data(
            f"TOOL ERROR: missing required param {e}", tool="search_code", path="",
        )


def _exec_analyze_transactions(action: "Action", ctx: "PackContext") -> str:
    params = action.params
    address = str(params.get("address", ""))
    try:
        fetcher = make_alchemy_fetcher(config.alchemy_api_key)
        res = analyze_transactions(
            params["address"], int(params.get("from_block", 0)),
            int(params.get("to_block", 0)), fetcher, focus=params.get("focus"),
        )
        body = "\n".join(res.notes) or "(no notable transactions)"
        return _ran_payload("analyze_transactions", body.splitlines(), ctx, address)
    except (OnChainError, KeyError) as e:
        return _payload_from_error(e, "analyze_transactions", ctx, address)


def _exec_run_slither(action: "Action", ctx: "PackContext") -> str:
    target = str(action.params.get("target", ""))
    try:
        findings = run_slither(
            target, ctx.scope_root, ctx.sandbox,
            timeout_s=config.chat_tool_timeout_s,
        )
    except (SlitherError, SandboxError, KeyError) as e:
        return _payload_from_error(e, "run_slither", ctx, target)
    lines = [f"{f.check}: {f.description}" for f in findings]
    return _ran_payload("run_slither", lines, ctx, target)


def _exec_run_mythril(action: "Action", ctx: "PackContext") -> str:
    target = str(action.params.get("target", ""))
    try:
        findings = run_mythril(
            target, ctx.scope_root, ctx.sandbox,
            timeout_s=config.chat_tool_timeout_s,
        )
    except (MythrilError, SandboxError, KeyError) as e:
        return _payload_from_error(e, "run_mythril", ctx, target)
    lines = [f"{f.title}: {f.description}" for f in findings]
    return _ran_payload("run_mythril", lines, ctx, target)


def _fail_closed_write_execute(action: "Action", ctx: "PackContext") -> str:
    """Reached only if a write_execute id slips past the kernel confirmation gate."""
    return ctx.wrap_data(
        "WRITE_EXECUTE cannot run from dispatch; confirmation required",
        tool=action.action_type, path="",
    )


_UNAVAILABLE_BUILD_GRAPH = "no sandbox adapter for host subprocess"
_UNAVAILABLE_DECOMPILE = "decompile_bytecode is dry-run only; no executable route"
_UNAVAILABLE_DEPLOY = "deploy_test_contract has no agent-path executor"


AGENT_TOOL_SURFACE: dict[str, SurfaceEntry] = {
    "read_file": SurfaceEntry(
        required_params=("path",),
        executor=_exec_read_file,
        offered=True,
        available=True,
        missing_precondition="",
        valid_params={"path": "Vault.sol"},
        summary="read a source file.",
    ),
    "search_code": SurfaceEntry(
        required_params=("pattern",),
        executor=_exec_search_code,
        offered=True,
        available=True,
        missing_precondition="",
        valid_params={"pattern": "withdraw"},
        summary="find where something is defined/used.",
    ),
    AuditActionType.run_slither.value: SurfaceEntry(
        required_params=("target",),
        executor=_exec_run_slither,
        offered=True,
        available=True,
        missing_precondition="",
        valid_params={"target": "Vault.sol"},
        summary="run Slither static analysis in the sandbox.",
    ),
    AuditActionType.run_mythril.value: SurfaceEntry(
        required_params=("target",),
        executor=_exec_run_mythril,
        offered=True,
        available=True,
        missing_precondition="",
        valid_params={"target": "Vault.sol"},
        summary="run Mythril symbolic execution in the sandbox.",
    ),
    AuditActionType.analyze_transactions.value: SurfaceEntry(
        required_params=("address",),
        executor=_exec_analyze_transactions,
        offered=False,
        available=True,
        missing_precondition="",
        valid_params={"address": "0x" + "ab" * 20},
        summary="fetch on-chain transactions (unoffered: no wall-clock deadline).",
    ),
    AuditActionType.write_poc.value: SurfaceEntry(
        required_params=("finding_id",),
        executor=_fail_closed_write_execute,
        offered=False,
        available=True,
        missing_precondition="",
        valid_params={"finding_id": "F1"},
        summary="write a PoC after out-of-band confirmation.",
    ),
    AuditActionType.run_tests.value: SurfaceEntry(
        required_params=("finding_id",),
        executor=_fail_closed_write_execute,
        offered=False,
        available=True,
        missing_precondition="",
        valid_params={"finding_id": "F1"},
        summary="run Foundry tests after out-of-band confirmation.",
    ),
    AuditActionType.build_graph.value: SurfaceEntry(
        required_params=(),
        executor=None,
        offered=False,
        available=False,
        missing_precondition=_UNAVAILABLE_BUILD_GRAPH,
        valid_params={},
        summary="build a call/data-flow graph (unavailable: host subprocess).",
    ),
    AuditActionType.decompile_bytecode.value: SurfaceEntry(
        required_params=("address",),
        executor=None,
        offered=False,
        available=False,
        missing_precondition=_UNAVAILABLE_DECOMPILE,
        valid_params={"address": "0x" + "ab" * 20},
        summary="decompile bytecode (unavailable: no production runner).",
    ),
    AuditActionType.deploy_test_contract.value: SurfaceEntry(
        required_params=("network",),
        executor=None,
        offered=False,
        available=False,
        missing_precondition=_UNAVAILABLE_DEPLOY,
        valid_params={"network": "anvil"},
        summary="deploy to anvil (unavailable: no agent-path executor).",
    ),
}


def offered_entries() -> list[tuple[str, SurfaceEntry]]:
    return [(k, v) for k, v in AGENT_TOOL_SURFACE.items() if v.offered]

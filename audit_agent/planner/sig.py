"""State Interference Graph (T053).

Deterministic, lightweight (no Slither needed): for each function, derive the
set of state variables it reads and writes, and whether it makes an external
call. Two functions *interfere* when one writes state the other touches; a
reentrancy edge exists when an externally-calling function shares state with
another. Stage 3 uses get_filtered_pairs to combine only findings whose
functions actually interact, instead of "same file".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from audit_agent.planner.stage1 import extract_functions

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_WRITE_RE = re.compile(r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])*\s*(?:=(?![=>])|\+=|-=|\*=|/=)")
_EXTERNAL_CALL = (".call", ".delegatecall", ".transfer(", ".send(", ".staticcall")
_DECL_SKIP = (
    "function", "modifier", "event", "struct", "enum", "constructor",
    "using", "import", "pragma", "error", "receive", "fallback", "return",
)


@dataclass
class FunctionNode:
    name: str
    reads: set[str] = field(default_factory=set)
    writes: set[str] = field(default_factory=set)
    has_external_call: bool = False


@dataclass
class StateInterferenceGraph:
    functions: dict[str, FunctionNode] = field(default_factory=dict)

    def interferes(self, a: str, b: str) -> bool:
        """True if functions a and b touch shared mutable state."""
        fa, fb = self.functions.get(a), self.functions.get(b)
        if not fa or not fb:
            return False
        return bool(
            (fa.writes & (fb.reads | fb.writes)) or (fb.writes & (fa.reads | fa.writes))
        )

    def can_reenter(self, a: str, b: str) -> bool:
        """True if a makes an external call and shares state with b."""
        fa = self.functions.get(a)
        return bool(fa and fa.has_external_call and self.interferes(a, b))


def extract_state_vars(source: str) -> set[str]:
    """Return contract-level (state) variable names via brace-depth tracking."""
    state_vars: set[str] = set()
    depth = 0
    buf: list[str] = []
    for ch in source:
        if ch == "{":
            depth += 1
            buf = []
        elif ch == "}":
            depth -= 1
            buf = []
        elif ch == ";":
            if depth == 1:
                name = _decl_var_name("".join(buf))
                if name:
                    state_vars.add(name)
            buf = []
        elif depth == 1:
            buf.append(ch)
    return state_vars


def _decl_var_name(stmt: str) -> str | None:
    stmt = stmt.strip()
    if not stmt:
        return None
    first = _IDENT_RE.match(stmt)
    if first and first.group(0) in _DECL_SKIP:
        return None
    decl = stmt.replace("=>", " ").split("=")[0]  # drop initializer, keep mapping
    ids = _IDENT_RE.findall(decl)
    return ids[-1] if ids else None


def build_sig(source: str) -> StateInterferenceGraph:
    """Build the interference graph for one Solidity source file."""
    state_vars = extract_state_vars(source)
    sig = StateInterferenceGraph()

    for name, body, _line in extract_functions(source):
        node = FunctionNode(name=name)
        node.has_external_call = any(tok in body for tok in _EXTERNAL_CALL)
        written = {m for m in _WRITE_RE.findall(body) if m in state_vars}
        referenced = {tok for tok in _IDENT_RE.findall(body) if tok in state_vars}
        node.writes = written
        node.reads = referenced - written
        sig.functions[name] = node

    return sig


def get_filtered_pairs(finding_locations: list[str], sig: StateInterferenceGraph) -> list[tuple[str, str]]:
    """Return interacting (loc_a, loc_b) finding-location pairs for Stage 3.

    Locations are "file:function"; pairing is by interfering functions.
    """
    pairs: list[tuple[str, str]] = []
    for i in range(len(finding_locations)):
        for j in range(i + 1, len(finding_locations)):
            fn_a = finding_locations[i].split(":")[-1]
            fn_b = finding_locations[j].split(":")[-1]
            if sig.interferes(fn_a, fn_b):
                pairs.append((finding_locations[i], finding_locations[j]))
    return pairs


# ── SmartGraphical graph → SIG (feature 002, US2) ────────────────────────────

def _node_short_name(node_id: str) -> str | None:
    """`function:Base._credit` -> `_credit`; `state:Base.balances` -> `balances`."""
    if ":" not in node_id:
        return None
    return node_id.split(":", 1)[1].split(".")[-1]


def parse_sg_graph(graph) -> dict:
    """Normalize a SmartGraphical graph payload to `{nodes, edges}`."""
    if isinstance(graph, dict) and "nodes" in graph and "edges" in graph:
        return {"nodes": graph.get("nodes", []), "edges": graph.get("edges", [])}
    ms = (graph or {}).get("model_summary", {}) if isinstance(graph, dict) else {}
    inner = ms.get("graph", {}) if isinstance(ms, dict) else {}
    return {"nodes": inner.get("nodes", []), "edges": inner.get("edges", [])}


def build_sig_from_smartgraphical(graph) -> StateInterferenceGraph:
    """Build the interference graph from SmartGraphical's structural edges.

    Read/write sets come from `state_to_function_*` (+ `cross_type_state_*`)
    edges; external-call flags from `function_to_system`/`function_to_object`.
    Crucially, state is propagated along `function_to_function`/`cross_type_call`
    edges: a caller inherits its callees' reads/writes (transitive, cycle-safe).
    This captures cross-inheritance state sharing that the single-file regex SIG
    cannot see (a child function calling an inherited state-mutating parent).
    """
    graph = parse_sg_graph(graph)
    sig = StateInterferenceGraph()

    for node in graph["nodes"]:
        if node.get("group") == "function":
            name = _node_short_name(node.get("id", "")) or ""
            if name:
                sig.functions.setdefault(name, FunctionNode(name=name))

    calls: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        kind = edge.get("kind", "")
        src = _node_short_name(edge.get("source", "") or "")
        tgt = _node_short_name(edge.get("target", "") or "")
        if kind in ("state_to_function_read", "cross_type_state_read"):
            if tgt in sig.functions and src:
                sig.functions[tgt].reads.add(src)
        elif kind in ("state_to_function_write", "cross_type_state_write"):
            if tgt in sig.functions and src:
                sig.functions[tgt].writes.add(src)
        elif kind in ("function_to_function", "cross_type_call"):
            if src in sig.functions and tgt:
                calls.setdefault(src, set()).add(tgt)
        elif kind in ("function_to_system", "function_to_object"):
            if src in sig.functions:
                sig.functions[src].has_external_call = True

    # Transitive propagation of callee state to callers (cycle-safe).
    def _reachable(start: str) -> set[str]:
        seen: set[str] = set()
        stack = list(calls.get(start, ()))
        while stack:
            nxt = stack.pop()
            if nxt in seen:
                continue
            seen.add(nxt)
            stack.extend(calls.get(nxt, ()))
        return seen

    for name, node in sig.functions.items():
        for callee in _reachable(name):
            other = sig.functions.get(callee)
            if other and callee != name:
                node.reads |= other.reads
                node.writes |= other.writes

    return sig

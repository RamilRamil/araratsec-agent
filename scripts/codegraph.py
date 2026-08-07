"""Code-comprehension graph over OUR OWN codebases (spec 017) — a dev tool.

Answers structural questions about the SR-agent repo (and the separate framework
project) — "who calls X", "what does module M import", "where is X defined",
"what connects X to Y" — without manual grepping.

Boundaries this module deliberately keeps (see specs/017-codegraph-comprehension/):
  - OFFLINE, no language model, no network, no paid API. The query layer is
    stdlib-only; the map is built by the external `graphify` CLI as a SUBPROCESS
    (tree-sitter AST, verified to run with all provider credentials unset).
  - graphify is a DEV/optional tool, never a project dependency and never
    `import`ed here — only invoked as a subprocess string.
  - The secure kernel (`sr_agent/**`) MUST NOT import this module, and the map is
    NEVER model grounding, an authorization input, or part of the trust hierarchy
    (enforced by tests/architecture/test_codegraph_isolation.py).
  - graphify cannot parse Solidity; audit-target grounding stays solely with
    scripts/solidity_index.py's SymbolIndex. This tool is for our own code only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

CALL_RELATIONS = {"calls"}
IMPORT_RELATIONS = {"imports", "imports_from"}
CHILD_RELATIONS = {"contains", "method"}
GRAPHIFY_TIMEOUT_S = 600  # cap `graphify extract` so a stuck run can't hang the caller forever


class CodeGraphFormatError(Exception):
    """graph.json is missing/malformed or its shape drifted from what we parse."""


class GraphifyMissing(Exception):
    """The external `graphify` CLI is not installed / not on PATH."""


def _parse_line(source_location: object) -> int | None:
    """graphify encodes location as e.g. "L5"; return the int, or None."""
    if isinstance(source_location, str) and source_location.startswith("L"):
        try:
            return int(source_location[1:])
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class CodeNode:
    id: str
    label: str
    file: str | None
    line: int | None
    kind: str
    origin: str | None

    @property
    def where(self) -> str:
        loc = self.file or "?"
        return f"{loc}:{self.line}" if self.line is not None else loc

    def render(self) -> str:
        return f"{self.label}  ({self.where})"


@dataclass(frozen=True)
class CodeEdge:
    source: str
    target: str
    relation: str
    confidence: str
    file: str | None
    line: int | None


def _node_kind(label: str, file_type: object) -> str:
    """Best-effort (not authoritative): a file node vs a symbol node."""
    if isinstance(label, str) and (label.endswith(".py") or "/" in label):
        return "module"
    return "symbol"


class CodeGraph:
    """In-memory, read-only view over a graphify node-link graph.json."""

    def __init__(self, nodes: dict[str, CodeNode],
                 out: dict[str, list[CodeEdge]],
                 in_: dict[str, list[CodeEdge]]) -> None:
        self.nodes = nodes
        self.out = out
        self.in_ = in_

    # ---- loading / validation -------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "CodeGraph":
        p = Path(path)
        if not p.exists():
            raise CodeGraphFormatError(
                f"code map not found: {p} — run `python scripts/codegraph.py build` first"
            )
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CodeGraphFormatError(f"code map is not valid JSON: {p}: {e}") from e
        return cls.from_dict(raw, source=str(p))

    @classmethod
    def from_dict(cls, raw: object, source: str = "<dict>") -> "CodeGraph":
        if not isinstance(raw, dict):
            raise CodeGraphFormatError(f"{source}: top level must be an object")
        node_list = raw.get("nodes")
        link_list = raw.get("links")
        if not isinstance(node_list, list):
            raise CodeGraphFormatError(f"{source}: missing/invalid 'nodes' list")
        if not isinstance(link_list, list):
            raise CodeGraphFormatError(f"{source}: missing/invalid 'links' list")

        nodes: dict[str, CodeNode] = {}
        for rec in node_list:
            if not isinstance(rec, dict) or "id" not in rec:
                raise CodeGraphFormatError(f"{source}: node without 'id': {rec!r}")
            nid = str(rec["id"])
            label = str(rec.get("label", nid))
            nodes[nid] = CodeNode(
                id=nid,
                label=label,
                file=rec.get("source_file"),
                line=_parse_line(rec.get("source_location")),
                kind=_node_kind(label, rec.get("file_type")),
                origin=rec.get("_origin"),
            )

        out: dict[str, list[CodeEdge]] = {}
        in_: dict[str, list[CodeEdge]] = {}
        for rec in link_list:
            if not isinstance(rec, dict) or not {"source", "target", "relation"} <= rec.keys():
                raise CodeGraphFormatError(
                    f"{source}: edge missing source/target/relation: {rec!r}"
                )
            edge = CodeEdge(
                source=str(rec["source"]),
                target=str(rec["target"]),
                relation=str(rec["relation"]),
                confidence=str(rec.get("confidence", "")),
                file=rec.get("source_file"),
                line=_parse_line(rec.get("source_location")),
            )
            out.setdefault(edge.source, []).append(edge)
            in_.setdefault(edge.target, []).append(edge)
        return cls(nodes, out, in_)

    # ---- helpers --------------------------------------------------------------

    def _edge_sort_key(self, e: CodeEdge) -> tuple:
        other = self.nodes.get(e.target) or self.nodes.get(e.source)
        f = (other.file or "") if other else ""
        ln = (other.line if other and other.line is not None else -1)
        return (f, ln, e.target, e.source, e.relation)

    def _sorted(self, edges: list[CodeEdge]) -> list[CodeEdge]:
        return sorted(edges, key=self._edge_sort_key)

    # ---- queries --------------------------------------------------------------

    def find(self, name: str) -> list[CodeNode]:
        """Resolve a name to node(s): by id, exact label, or normalized label."""
        if name in self.nodes:
            return [self.nodes[name]]

        def norm(s: str) -> str:
            return s.strip().lstrip(".").rstrip("()").strip()

        target = norm(name)
        matches = [n for n in self.nodes.values() if norm(n.label) == target or n.id == name]
        return sorted(matches, key=lambda n: (n.file or "", n.line or -1, n.id))

    def define(self, name: str) -> list[CodeNode]:
        return self.find(name)

    def neighbors(self, node_id: str) -> list[CodeEdge]:
        return self._sorted(self.out.get(node_id, []) + self.in_.get(node_id, []))

    def callers(self, node_id: str) -> list[CodeEdge]:
        return self._sorted([e for e in self.in_.get(node_id, []) if e.relation in CALL_RELATIONS])

    def callees(self, node_id: str) -> list[CodeEdge]:
        return self._sorted([e for e in self.out.get(node_id, []) if e.relation in CALL_RELATIONS])

    def dependencies(self, node_id: str) -> list[CodeEdge]:
        return self._sorted(
            [e for e in self.out.get(node_id, []) if e.relation in IMPORT_RELATIONS]
        )

    def path(self, a: str, b: str) -> list[CodeEdge]:
        """Shortest relationship chain a→b via unweighted BFS over out-edges."""
        if a == b:
            return []
        prev: dict[str, CodeEdge] = {}
        seen = {a}
        q: deque[str] = deque([a])
        while q:
            cur = q.popleft()
            for e in self.out.get(cur, []):
                if e.target in seen:
                    continue
                seen.add(e.target)
                prev[e.target] = e
                if e.target == b:
                    chain: list[CodeEdge] = []
                    node = b
                    while node in prev:
                        chain.append(prev[node])
                        node = prev[node].source
                    return list(reversed(chain))
                q.append(e.target)
        return []

    def module_summary(self, node_id: str) -> dict:
        children = self._sorted(
            [e for e in self.out.get(node_id, []) if e.relation in CHILD_RELATIONS]
        )
        return {
            "children": children,
            "inbound": len(self.in_.get(node_id, [])),
            "outbound": len(self.out.get(node_id, [])),
        }


# ---- build (external graphify subprocess) -------------------------------------


def build_graph(root: str | Path) -> Path:
    """Run `graphify extract <root> --no-viz` (offline) and return graph.json path.

    Inherits the environment; verified to succeed with no provider credentials.
    Writes only under <root>/graphify-out/ — the source tree is left untouched.
    """
    root = Path(root).resolve()
    if shutil.which("graphify") is None:
        raise GraphifyMissing(
            "graphify not found — install it with: uv tool install graphifyy"
        )
    # --code-only: index code via local tree-sitter AST ONLY (no key, no network).
    # Without it, a repo containing docs (.md/.txt) makes graphify demand an LLM key
    # for semantic extraction of those files — which would break the offline guarantee.
    # --no-viz: skip the HTML render, keep graph.json + report.
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, our own trusted repo
            ["graphify", "extract", str(root), "--code-only", "--no-viz"],
            capture_output=True,
            text=True,
            timeout=GRAPHIFY_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        # A stuck extraction must not hang the caller indefinitely (no timeout before).
        raise CodeGraphFormatError(
            f"graphify extract timed out after {GRAPHIFY_TIMEOUT_S}s on {root}"
        ) from e
    if proc.returncode != 0:
        raise CodeGraphFormatError(
            f"graphify extract failed ({proc.returncode}): {proc.stderr.strip()[-500:]}"
        )
    graph_path = root / "graphify-out" / "graph.json"
    if not graph_path.exists():
        raise CodeGraphFormatError(
            f"graphify ran but no graph.json at {graph_path}"
        )
    return graph_path


# ---- CLI ----------------------------------------------------------------------


def _default_graph_path(root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parents[1]
    return root / "graphify-out" / "graph.json"


def _print_nodes(nodes: list[CodeNode]) -> None:
    for n in nodes:
        print(n.render())


def _print_edges(g: CodeGraph, edges: list[CodeEdge], toward: str) -> None:
    for e in edges:
        other_id = e.source if toward == "source" else e.target
        other = g.nodes.get(other_id)
        label = other.render() if other else other_id
        print(f"{label}   [{e.relation} {e.confidence}]")


def _resolve_single(g: CodeGraph, name: str) -> CodeNode | None:
    hits = g.find(name)
    if not hits:
        print(f"not found: {name}", file=sys.stderr)
        return None
    if len(hits) > 1:
        print(f"ambiguous: {name} — matches:", file=sys.stderr)
        for n in hits:
            print(f"  {n.id}  ({n.where})", file=sys.stderr)
        # Use the first deterministically; caller can re-query by exact id.
    return hits[0]


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        path = build_graph(args.root)
    except GraphifyMissing as e:
        print(str(e), file=sys.stderr)
        return 2
    except CodeGraphFormatError as e:
        print(str(e), file=sys.stderr)
        return 1
    g = CodeGraph.load(path)
    print(f"built {path}  ({len(g.nodes)} nodes, "
          f"{sum(len(v) for v in g.out.values())} edges)")
    return 0


def _load_for_query(args: argparse.Namespace) -> CodeGraph | None:
    path = Path(args.graph) if args.graph else _default_graph_path()
    try:
        return CodeGraph.load(path)
    except CodeGraphFormatError as e:
        print(str(e), file=sys.stderr)
        return None


def _cmd_query(args: argparse.Namespace) -> int:
    g = _load_for_query(args)
    if g is None:
        return 1

    if args.command in {"define"}:
        hits = g.find(args.name)
        if not hits:
            print(f"not found: {args.name}", file=sys.stderr)
            return 1
        _print_nodes(hits)
        return 0

    if args.command == "path":
        a = _resolve_single(g, args.a)
        b = _resolve_single(g, args.b)
        if a is None or b is None:
            return 1
        chain = g.path(a.id, b.id)
        if not chain:
            print(f"no path found: {a.id} -> {b.id}", file=sys.stderr)
            return 1
        for e in chain:
            src = g.nodes.get(e.source)
            tgt = g.nodes.get(e.target)
            print(f"{src.render() if src else e.source}  --{e.relation}-->  "
                  f"{tgt.render() if tgt else e.target}   [{e.confidence}]")
        return 0

    node = _resolve_single(g, args.name)
    if node is None:
        return 1
    if args.command == "callers":
        _print_edges(g, g.callers(node.id), toward="source")
    elif args.command == "callees":
        _print_edges(g, g.callees(node.id), toward="target")
    elif args.command == "deps":
        _print_edges(g, g.dependencies(node.id), toward="target")
    elif args.command == "neighbors":
        _print_edges(g, g.neighbors(node.id), toward="target")
    elif args.command == "module":
        s = g.module_summary(node.id)
        print(f"{node.render()}  — inbound {s['inbound']}, outbound {s['outbound']}")
        _print_edges(g, s["children"], toward="target")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codegraph",
        description="Offline structural queries over our own code (spec 017 dev tool).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build/refresh the map for a repo root")
    b.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[1]),
                   help="repository root (default: this repo)")
    b.set_defaults(func=_cmd_build)

    for name, help_text, needs in [
        ("define", "where a symbol is defined", "name"),
        ("callers", "who calls a symbol", "name"),
        ("callees", "what a symbol calls", "name"),
        ("deps", "what a module/symbol imports", "name"),
        ("neighbors", "all direct connections", "name"),
        ("module", "module summary", "name"),
    ]:
        q = sub.add_parser(name, help=help_text)
        q.add_argument("name")
        q.add_argument("--graph", help="path to graph.json (default: <repo>/graphify-out/)")
        q.set_defaults(func=_cmd_query)

    pp = sub.add_parser("path", help="shortest relationship chain A -> B")
    pp.add_argument("a")
    pp.add_argument("b")
    pp.add_argument("--graph", help="path to graph.json")
    pp.set_defaults(func=_cmd_query)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

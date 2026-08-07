"""Scaffold API inventory (feature 041).

Derives a bounded, DATA-marked inventory of usable inherited scaffold symbols
via source-qualified per-edge parent resolution (FR-013/FR-014). Does NOT reuse
024 `_base_state_vars` or bare `SymbolIndex._bases` for parent identity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from solidity_parser import parser as _sol_parser

from scripts.solidity_index import _type_str

INVENTORY_BUDGET = 4000
HINT_EXCERPT_BUDGET = 1500

_LIFECYCLE_RE = re.compile(r"^setUp")
_CALLABLE_RE = re.compile(r"^_(deploy|grant|deposit)")


@dataclass(frozen=True)
class InventoryStateVar:
    name: str
    type_text: str
    declaring_contract: str
    declaring_path: str
    distance: int
    visibility: str


@dataclass(frozen=True)
class InventoryHelper:
    name: str
    param_types: tuple[str, ...]
    declaring_contract: str
    declaring_path: str
    distance: int
    visibility: str
    section: str  # "lifecycle" | "callable"

    @property
    def canonical_param_types(self) -> str:
        return ",".join(self.param_types)


@dataclass(frozen=True)
class UnresolvedParent:
    name: str
    from_contract: str
    from_path: str
    reason: str  # missing | unparseable | ambiguous


@dataclass(frozen=True)
class DiamondDrop:
    name: str
    discarded: dict
    winning: dict


@dataclass
class ScaffoldApiInventory:
    leaf_contract: str
    leaf_path: str
    state_vars: list[InventoryStateVar] = field(default_factory=list)
    lifecycle: list[InventoryHelper] = field(default_factory=list)
    callable_helpers: list[InventoryHelper] = field(default_factory=list)
    unresolved_parents: list[UnresolvedParent] = field(default_factory=list)
    diamond_drops: list[DiamondDrop] = field(default_factory=list)
    rendered_body: str = ""
    degraded: bool = False

    @property
    def data_block(self) -> str:
        return (
            "[DATA START scaffold_api]\n"
            f"{self.rendered_body}\n"
            "[DATA END scaffold_api]"
        )


@dataclass(frozen=True)
class EdgeResolution:
    parent_name: str
    resolved_path: Path | None
    via: str | None  # same_file | import | None
    reason: str | None
    candidates: tuple[Path, ...] = ()
    resolved_contract_name: str | None = None  # name inside resolved_path (may differ from alias)


def _parse_source(source: str) -> dict | None:
    try:
        return _sol_parser.parse(source)
    except Exception:
        return None


def _load_text(path: Path, file_map: dict[Path, str] | None) -> str | None:
    if file_map is not None:
        for k, v in file_map.items():
            if Path(k).resolve() == path.resolve() or Path(k) == path:
                return v
        # also try string keys / basename match within map
        for k, v in file_map.items():
            if Path(k).name == path.name and path.name in str(k):
                return v
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _contracts_in_ast(ast: dict) -> list[dict]:
    return [c for c in ast.get("children", []) if c.get("type") == "ContractDefinition"]


def _imports_in_ast(ast: dict) -> list[dict]:
    return [c for c in ast.get("children", []) if c.get("type") == "ImportDirective"]


def _base_names(contract: dict) -> list[str]:
    out: list[str] = []
    for b in contract.get("baseContracts") or []:
        name = (b.get("baseName") or {}).get("namePath")
        if name:
            out.append(name)
    return out


def _contract_names_in_source(source: str) -> list[str]:
    ast = _parse_source(source)
    if not ast:
        return []
    return [c.get("name", "") for c in _contracts_in_ast(ast) if c.get("name")]


def _pick_leaf_contract(ast: dict) -> str | None:
    contracts = _contracts_in_ast(ast)
    if not contracts:
        return None
    names = {c.get("name") for c in contracts if c.get("name")}
    used_as_base: set[str] = set()
    for c in contracts:
        for b in _base_names(c):
            if b in names:
                used_as_base.add(b)
    derived = [c for c in contracts if c.get("name") and c.get("name") not in used_as_base]
    if len(derived) == 1:
        return derived[0].get("name")
    with_bases = [c for c in derived if _base_names(c)]
    if len(with_bases) == 1:
        return with_bases[0].get("name")
    if len(contracts) == 1:
        return contracts[0].get("name")
    return None


def _apply_remappings(import_path: str, remappings: list[str]) -> str:
    for raw in remappings:
        if "=" not in raw:
            continue
        prefix, target = raw.split("=", 1)
        if import_path.startswith(prefix):
            return target + import_path[len(prefix):]
    return import_path


def _resolve_import_path(
    child_path: Path, import_path: str, remappings: list[str],
) -> Path:
    mapped = _apply_remappings(import_path, remappings)
    p = Path(mapped)
    if p.is_absolute():
        return p.resolve()
    return (child_path.parent / p).resolve()


def resolve_parent_edge(
    *,
    child_path: Path,
    child_source: str,
    parent_name: str,
    file_map: dict[Path, str] | None = None,
    remappings: list[str] | None = None,
) -> EdgeResolution:
    """FR-013: unique same-file first (short-circuit), else direct imports."""
    remappings = remappings or []
    ast = _parse_source(child_source)
    if not ast:
        return EdgeResolution(parent_name, None, None, "unparseable")

    same = [c for c in _contracts_in_ast(ast) if c.get("name") == parent_name]
    if len(same) == 1:
        return EdgeResolution(
            parent_name, child_path.resolve(), "same_file", None,
            resolved_contract_name=parent_name,
        )
    if len(same) > 1:
        return EdgeResolution(parent_name, None, None, "ambiguous", (child_path.resolve(),))

    candidates: list[tuple[Path, str]] = []
    for imp in _imports_in_ast(ast):
        ipath = imp.get("path") or ""
        if not ipath:
            continue
        target = _resolve_import_path(child_path, ipath, remappings)
        text = _load_text(target, file_map)
        if text is None:
            continue
        aliases = imp.get("symbolAliases") or {}
        if aliases:
            local_to_remote = {local: remote for remote, local in aliases.items() if local}
            if parent_name in local_to_remote:
                seek = local_to_remote[parent_name]
            elif parent_name in aliases and (
                not aliases[parent_name] or aliases[parent_name] == parent_name
            ):
                seek = parent_name
            else:
                continue
        else:
            seek = parent_name
        names = _contract_names_in_source(text)
        if seek in names:
            candidates.append((target.resolve(), seek))

    uniq: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for path, seek in candidates:
        if path not in seen:
            seen.add(path)
            uniq.append((path, seek))

    if len(uniq) == 1:
        path, seek = uniq[0]
        return EdgeResolution(
            parent_name, path, "import", None, resolved_contract_name=seek,
        )
    if not uniq:
        return EdgeResolution(parent_name, None, None, "missing")
    return EdgeResolution(
        parent_name, None, None, "ambiguous", tuple(p for p, _ in uniq),
    )


def _param_type_list(fn: dict) -> tuple[str, ...]:
    params = fn.get("parameters") or {}
    out: list[str] = []
    for p in params.get("parameters") or []:
        out.append(_type_str(p.get("typeName")))
    return tuple(out)


def _usable_visibility_var(vis: str | None) -> bool:
    if not vis or vis == "default":
        return True
    return vis in ("public", "internal")


def _usable_visibility_fn(vis: str | None) -> bool:
    return (vis or "") in ("public", "internal")


def _collect_from_contract(
    contract: dict,
    path: Path,
    distance: int,
) -> tuple[list[InventoryStateVar], list[InventoryHelper], list[InventoryHelper]]:
    cname = contract.get("name") or "?"
    path_s = str(path)
    state: list[InventoryStateVar] = []
    life: list[InventoryHelper] = []
    call: list[InventoryHelper] = []
    for sub in contract.get("subNodes") or []:
        t = sub.get("type")
        if t == "StateVariableDeclaration":
            for v in sub.get("variables") or []:
                name = v.get("name")
                if not name:
                    continue
                vis = v.get("visibility") or "default"
                if vis == "private":
                    continue
                if not _usable_visibility_var(vis):
                    continue
                state.append(InventoryStateVar(
                    name=name,
                    type_text=_type_str(v.get("typeName")),
                    declaring_contract=cname,
                    declaring_path=path_s,
                    distance=distance,
                    visibility=vis if vis != "default" else "default",
                ))
        elif t == "FunctionDefinition" and sub.get("name"):
            name = sub["name"]
            vis = sub.get("visibility") or ""
            if not _usable_visibility_fn(vis):
                continue
            params = _param_type_list(sub)
            if _LIFECYCLE_RE.match(name):
                life.append(InventoryHelper(
                    name=name, param_types=params, declaring_contract=cname,
                    declaring_path=path_s, distance=distance, visibility=vis,
                    section="lifecycle",
                ))
            elif _CALLABLE_RE.match(name):
                call.append(InventoryHelper(
                    name=name, param_types=params, declaring_contract=cname,
                    declaring_path=path_s, distance=distance, visibility=vis,
                    section="callable",
                ))
    return state, life, call


def _entry_line_state(sv: InventoryStateVar) -> str:
    return f"{sv.type_text} {sv.name}  # {sv.declaring_contract} d={sv.distance}"


def _entry_line_helper(h: InventoryHelper) -> str:
    return f"{h.name}({h.canonical_param_types})  # {h.declaring_contract} d={h.distance}"


def _truncate_entries(entries: list[str], budget: int) -> list[str]:
    out: list[str] = []
    used = 0
    for e in entries:
        add = len(e) + (1 if out else 0)
        if used + add > budget:
            break
        out.append(e)
        used += add
    return out


def render_inventory(inv: ScaffoldApiInventory, budget: int = INVENTORY_BUDGET) -> str:
    """Render body (no DATA markers) under FR-004 priority + budget."""
    header = f"leaf={inv.leaf_contract} file={Path(inv.leaf_path).name}"
    guidance = (
        "lifecycle_setup: use in the setup path (follow base example / "
        "super.setUp() when overriding); not a normal test-body call."
    )

    def sort_state(items: list[InventoryStateVar]) -> list[InventoryStateVar]:
        return sorted(items, key=lambda x: (x.distance, x.name, x.declaring_contract))

    def sort_help(items: list[InventoryHelper]) -> list[InventoryHelper]:
        return sorted(
            items,
            key=lambda x: (x.distance, x.name, x.canonical_param_types, x.declaring_contract),
        )

    # FR-004 buckets
    buckets: list[list[str]] = [
        [_entry_line_state(s) for s in sort_state([s for s in inv.state_vars if s.distance == 0])],
        [_entry_line_helper(h) for h in sort_help([h for h in inv.lifecycle if h.distance == 0])],
        [_entry_line_helper(h) for h in sort_help([h for h in inv.callable_helpers if h.distance == 0])],
    ]
    max_d = 0
    for s in inv.state_vars:
        max_d = max(max_d, s.distance)
    for h in inv.lifecycle + inv.callable_helpers:
        max_d = max(max_d, h.distance)
    for d in range(1, max_d + 1):
        buckets.append([_entry_line_state(s) for s in sort_state([s for s in inv.state_vars if s.distance == d])])
        buckets.append([_entry_line_helper(h) for h in sort_help([h for h in inv.lifecycle if h.distance == d])])
        buckets.append([_entry_line_helper(h) for h in sort_help([h for h in inv.callable_helpers if h.distance == d])])

    # Reserve space for headers/sections approximately
    fixed = header + "\n## state_variables\n## lifecycle_setup\n" + guidance + "\n## callable_helpers\n"
    if inv.unresolved_parents:
        fixed += "## unresolved_parents\n"
        for u in inv.unresolved_parents:
            fixed += f"{u.name} from {u.from_contract} reason={u.reason}\n"
    remain = max(0, budget - len(fixed))

    section_for: list[tuple[str, list[str]]] = []
    section_for.append(("state", buckets[0]))
    section_for.append(("life", buckets[1]))
    section_for.append(("call", buckets[2]))
    bi = 3
    while bi < len(buckets):
        section_for.append(("state", buckets[bi]))
        section_for.append(("life", buckets[bi + 1]))
        section_for.append(("call", buckets[bi + 2]))
        bi += 3

    kept_state: list[str] = []
    kept_life: list[str] = []
    kept_call: list[str] = []
    used = 0
    for sec, lines in section_for:
        for line in lines:
            add = len(line) + 1
            if used + add > remain:
                # stop entirely under budget
                lines = []
                break
            if sec == "state":
                kept_state.append(line)
            elif sec == "life":
                kept_life.append(line)
            else:
                kept_call.append(line)
            used += add
        else:
            continue
        break

    parts = [header, "## state_variables"]
    parts.extend(kept_state)
    parts.append("## lifecycle_setup")
    parts.append(guidance)
    parts.extend(kept_life)
    parts.append("## callable_helpers")
    parts.extend(kept_call)
    if inv.unresolved_parents:
        parts.append("## unresolved_parents")
        for u in inv.unresolved_parents:
            parts.append(f"{u.name} from {u.from_contract} reason={u.reason}")
    body = "\n".join(parts)
    if len(body) > budget:
        # hard cap: drop from end of callable then life then state while keeping headers
        body = body[:budget]
        # prefer whole lines
        body = "\n".join(body.splitlines()[:-1]) if "\n" in body else body
    return body


def hint_excerpt(inv: ScaffoldApiInventory, budget: int = HINT_EXCERPT_BUDGET) -> str:
    return render_inventory(inv, budget=budget)


def build_inventory(
    leaf_path: Path,
    *,
    project: Path | None = None,
    file_map: dict[Path, str] | None = None,
    remappings: list[str] | None = None,
    leaf_contract: str | None = None,
) -> ScaffoldApiInventory | None:
    """Build inventory for a single leaf file. None if leaf unparseable."""
    remappings = remappings or []
    leaf_path = leaf_path.resolve()
    source = _load_text(leaf_path, file_map)
    if source is None:
        return None
    ast = _parse_source(source)
    if not ast:
        return None
    cname = leaf_contract or _pick_leaf_contract(ast)
    if not cname:
        return None
    leaf_node = next((c for c in _contracts_in_ast(ast) if c.get("name") == cname), None)
    if leaf_node is None:
        return None

    state_vars: list[InventoryStateVar] = []
    lifecycle: list[InventoryHelper] = []
    callable_helpers: list[InventoryHelper] = []
    unresolved: list[UnresolvedParent] = []
    diamond_drops: list[DiamondDrop] = []

    # BFS walk: (contract_node, path, source, distance)
    queue: list[tuple[dict, Path, str, int]] = [(leaf_node, leaf_path, source, 0)]
    seen_edges: set[tuple[str, str, int]] = set()  # parent_name, from_path, dist
    visited_contracts: set[tuple[str, str]] = set()  # name, path

    while queue:
        node, path, src, dist = queue.pop(0)
        key = (node.get("name") or "?", str(path.resolve()))
        if key in visited_contracts:
            continue
        visited_contracts.add(key)
        s, l, c = _collect_from_contract(node, path, dist)
        state_vars.extend(s)
        lifecycle.extend(l)
        callable_helpers.extend(c)

        for parent_name in _base_names(node):
            ek = (parent_name, str(path.resolve()), dist)
            if ek in seen_edges:
                continue
            seen_edges.add(ek)
            edge = resolve_parent_edge(
                child_path=path,
                child_source=src,
                parent_name=parent_name,
                file_map=file_map,
                remappings=remappings,
            )
            if edge.resolved_path is None:
                unresolved.append(UnresolvedParent(
                    name=parent_name,
                    from_contract=node.get("name") or "?",
                    from_path=str(path),
                    reason=edge.reason or "missing",
                ))
                continue
            ptext = _load_text(edge.resolved_path, file_map)
            if ptext is None:
                unresolved.append(UnresolvedParent(
                    name=parent_name,
                    from_contract=node.get("name") or "?",
                    from_path=str(path),
                    reason="missing",
                ))
                continue
            past = _parse_source(ptext)
            if not past:
                unresolved.append(UnresolvedParent(
                    name=parent_name,
                    from_contract=node.get("name") or "?",
                    from_path=str(path),
                    reason="unparseable",
                ))
                continue
            # parent may be same-file under a different contract name; aliases use resolved_contract_name
            seek_name = edge.resolved_contract_name or parent_name
            pnode = next(
                (c for c in _contracts_in_ast(past) if c.get("name") == seek_name),
                None,
            )
            if pnode is None:
                unresolved.append(UnresolvedParent(
                    name=parent_name,
                    from_contract=node.get("name") or "?",
                    from_path=str(path),
                    reason="missing",
                ))
                continue
            queue.append((pnode, edge.resolved_path, ptext, dist + 1))

    # Dedup state vars; diamond type collision
    by_name: dict[str, list[InventoryStateVar]] = {}
    for sv in state_vars:
        by_name.setdefault(sv.name, []).append(sv)
    final_state: list[InventoryStateVar] = []
    for name, group in by_name.items():
        # unique by declaring_contract
        by_decl: dict[str, InventoryStateVar] = {}
        for sv in group:
            prev = by_decl.get(sv.declaring_contract)
            if prev is None or sv.distance < prev.distance:
                by_decl[sv.declaring_contract] = sv
        decls = list(by_decl.values())
        types = {d.type_text for d in decls}
        if len(types) > 1 and len(decls) > 1:
            winner = min(decls, key=lambda d: (d.distance, d.declaring_contract))
            for d in decls:
                if d is winner:
                    continue
                if d.type_text != winner.type_text:
                    diamond_drops.append(DiamondDrop(
                        name=name,
                        discarded={
                            "contract": d.declaring_contract,
                            "path": d.declaring_path,
                            "type_text": d.type_text,
                            "distance": d.distance,
                        },
                        winning={
                            "contract": winner.declaring_contract,
                            "path": winner.declaring_path,
                            "type_text": winner.type_text,
                            "distance": winner.distance,
                        },
                    ))
            final_state.append(winner)
        else:
            final_state.extend(decls)

    # Dedup helpers by full overload key
    def dedup_helpers(items: list[InventoryHelper]) -> list[InventoryHelper]:
        seen: set[tuple] = set()
        out: list[InventoryHelper] = []
        for h in items:
            k = (h.declaring_contract, h.section, h.name, h.canonical_param_types)
            if k in seen:
                continue
            seen.add(k)
            out.append(h)
        return out

    inv = ScaffoldApiInventory(
        leaf_contract=cname,
        leaf_path=str(leaf_path),
        state_vars=final_state,
        lifecycle=dedup_helpers(lifecycle),
        callable_helpers=dedup_helpers(callable_helpers),
        unresolved_parents=unresolved,
        diamond_drops=diamond_drops,
        degraded=bool(unresolved or diamond_drops),
    )
    inv.rendered_body = render_inventory(inv)
    return inv


def derive_or_omit(
    scaffold_paths: list[Path],
    *,
    project: Path | None = None,
    file_map: dict[Path, str] | None = None,
    remappings: list[str] | None = None,
) -> tuple[ScaffoldApiInventory | None, str | None]:
    """FR-014: len==0 -> (None, None); len>1 -> (None, ambiguous_leaf);
    len==1 -> inventory or (None, leaf_unparseable).
    """
    if not scaffold_paths:
        return None, None
    if len(scaffold_paths) > 1:
        return None, "ambiguous_leaf"
    inv = build_inventory(
        scaffold_paths[0],
        project=project,
        file_map=file_map,
        remappings=remappings,
    )
    if inv is None:
        return None, "leaf_unparseable"
    return inv, None

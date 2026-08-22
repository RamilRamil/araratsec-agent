"""AST-backed Solidity symbol index (feature 007).

Replaces `scripts/poc_queue_runner.py`'s regex-based extraction (a hand-rolled
function-signature regex, a hand-rolled modifier extractor, ad-hoc file-name
matching) with a real parse of the target project's grammar, via the
`solidity-parser` package (ANTLR4-based; see specs/007-ast-grounded-poc-drafting/
research.md R1 for why this library over tree-sitter-solidity).

Walks the RAW parse tree (not `solidity_parser.parser.objectify`, whose
`FunctionObject` wrapper drops modifier information — verified empirically against
this project's real `DemoCooldown.cancel`, research.md's own validation) so every
`Symbol.definition` — a struct's fields, a function's full signature AND its real
access-control modifiers, an enum's values — is grammar-correct, never guessed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from solidity_parser import parser as _sol_parser

logger = logging.getLogger(__name__)

_SYMBOL_KINDS = ("contract", "interface", "struct", "enum", "function", "modifier", "state_var")


@dataclass(frozen=True)
class Symbol:
    """A named Solidity construct discovered by parsing the target project.

    `definition` is always derived from the parsed AST, never hand-assembled from a
    text pattern — this is what makes it trustworthy as ground truth (spec 007 FR-002).
    """
    name: str
    kind: str                    # one of _SYMBOL_KINDS
    contract: str                # containing contract/interface name ("" for top-level)
    file: Path
    definition: str              # the real, complete rendering
    modifiers: tuple[str, ...] = field(default_factory=tuple)  # only for kind == "function"
    visibility: str = ""         # only for kind == "function" (external/public/internal/private/"")


def _type_str(type_node: dict | None) -> str:
    """Render a parameter/field's typeName node back to Solidity source text.
    Falls back to a raw repr for any node shape not explicitly handled — never
    raises, since an unusual type must not take down the whole index build (R8)."""
    if type_node is None:
        return "?"
    t = type_node.get("type")
    if t == "ElementaryTypeName":
        return type_node.get("name", "?")
    if t == "UserDefinedTypeName":
        return type_node.get("namePath", "?")
    if t == "ArrayTypeName":
        base = _type_str(type_node.get("baseTypeName"))
        length = type_node.get("length")
        return f"{base}[{length if length is not None else ''}]"
    if t == "Mapping":
        key = _type_str(type_node.get("keyType"))
        val = _type_str(type_node.get("valueType"))
        return f"mapping({key} => {val})"
    return str(type_node.get("name") or type_node.get("namePath") or t or "?")


def _param_str(p: dict) -> str:
    parts = [_type_str(p.get("typeName"))]
    if p.get("storageLocation"):
        parts.append(p["storageLocation"])
    if p.get("name"):
        parts.append(p["name"])
    return " ".join(parts)


def _params_str(param_list: dict | None) -> str:
    if not param_list:
        return ""
    return ", ".join(_param_str(p) for p in param_list.get("parameters", []))


def _render_function(fn: dict) -> tuple[str, tuple[str, ...], str]:
    """(definition text, modifier invocation strings, visibility) for a raw
    FunctionDefinition node."""
    name = fn.get("name") or ("constructor" if fn.get("isConstructor") else "<fallback/receive>")
    params = _params_str(fn.get("parameters"))
    visibility = fn.get("visibility") or ""
    tail: list[str] = []
    if visibility:
        tail.append(visibility)
    if fn.get("stateMutability"):
        tail.append(fn["stateMutability"])
    mods: list[str] = []
    for m in fn.get("modifiers") or []:
        mname = m.get("name", "?")
        margs = m.get("arguments") or []
        if margs:
            arg_strs = [a.get("name") or a.get("number") or _type_str(a) for a in margs]
            mods.append(f"{mname}({', '.join(str(a) for a in arg_strs)})")
        else:
            mods.append(mname)
    tail.extend(mods)
    ret = _params_str(fn.get("returnParameters"))
    sig = f"function {name}({params}) {' '.join(tail)}".rstrip()
    if ret:
        sig += f" returns ({ret})"
    return sig + ";", tuple(mods), visibility


def _render_struct(node: dict) -> str:
    lines = [f"struct {node.get('name', '?')} {{"]
    for m in node.get("members", []):
        lines.append(f"    {_type_str(m.get('typeName'))} {m.get('name', '?')};")
    lines.append("}")
    return "\n".join(lines)


def _render_enum(node: dict) -> str:
    values = [m.get("name", "?") for m in node.get("members", [])]
    return f"enum {node.get('name', '?')} {{ {', '.join(values)} }}"


def _render_state_var(node: dict) -> str:
    parts = []
    for v in node.get("variables", []):
        vis = v.get("visibility")
        bits = [_type_str(v.get("typeName"))]
        if vis and vis != "default":
            bits.append(vis)
        bits.append(v.get("name", "?"))
        parts.append(" ".join(bits) + ";")
    return "\n".join(parts)


class SymbolIndex:
    """Queryable index of every named Solidity construct in a target project.

    Built once per harness run (data-model.md). `lookup(name)` returns every real
    match — never guesses a single "best" one under ambiguity (research.md R3): the
    same name can legitimately appear in more than one contract, or as overloaded
    functions.
    """

    def __init__(self) -> None:
        self._symbols: dict[str, list[Symbol]] = {}
        self._by_file: dict[Path, list[Symbol]] = {}
        # Inheritance + declared state-variable TYPES per contract (feature 009 US3):
        # lets a caller resolve "does this contract, or any of its ancestors, hold an
        # instance of type X?" — the cross-file inheritance a single-file regex is
        # blind to. `_bases[C]` = C's direct base-contract names; `_svtypes[C]` = the
        # types C declares directly as state variables.
        self._bases: dict[str, tuple[str, ...]] = {}
        self._svtypes: dict[str, set[str]] = {}
        self.unparsed_files: list[Path] = []

    def provides_state_var_type(self, contract: str, type_name: str) -> bool:
        """Does `contract` — or any contract in its transitive inheritance chain —
        declare a state variable of type `type_name`? Grammar-correct and
        cross-file (feature 009 US3), unlike a single-file regex. Unknown
        contracts (not indexed) contribute nothing; cycles are guarded."""
        seen: set[str] = set()
        stack = [contract]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            if type_name in self._svtypes.get(c, ()):
                return True
            stack.extend(self._bases.get(c, ()))
        return False

    def is_subtype(self, sub_type: str, ancestor_type: str) -> bool:
        """True iff `sub_type` equals or transitively inherits `ancestor_type`.
        A state variable declared as `sub_type` provides an instance usable
        wherever `ancestor_type` is needed (Liskov): e.g. a var typed
        `ChildVault` satisfies a finding that needs `BaseVault`, because
        `ChildVault is BaseVault`. Reflexive; a type absent from the index
        yields only the reflexive match (no inheritance known); cycles guarded."""
        if sub_type == ancestor_type:
            return True
        seen: set[str] = set()
        stack = list(self._bases.get(sub_type, ()))
        while stack:
            b = stack.pop()
            if b in seen:
                continue
            seen.add(b)
            if b == ancestor_type:
                return True
            stack.extend(self._bases.get(b, ()))
        return False

    def state_var_types(self, contract: str) -> set[str]:
        """Every state-variable TYPE `contract` declares directly or via any
        ancestor (transitive). Companion to `provides_state_var_type` for callers
        that must subtype-match the declared type against a needed base rather
        than exact-match it. Cycles guarded; unknown contracts contribute nothing."""
        seen: set[str] = set()
        out: set[str] = set()
        stack = [contract]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            out |= self._svtypes.get(c, set())
            stack.extend(self._bases.get(c, ()))
        return out

    def lookup(self, name: str) -> list[Symbol]:
        """Exact match on `name`; if that misses and `name` is a `Contract.Symbol`
        qualified reference, fall back to the bare suffix (live H-01 run,
        2026-07-05: the model asked for `IDemoCooldown.TDemoGuard` and got a
        false not-found even though `TDemoGuard` genuinely exists in the index
        under its bare name — the index is keyed on bare names throughout)."""
        matches = list(self._symbols.get(name, []))
        if not matches and "." in name:
            bare = name.rsplit(".", 1)[-1]
            matches = list(self._symbols.get(bare, []))
        return matches

    def nested_container(self, name: str) -> str | None:
        """The containing contract/interface iff `name` is UNAMBIGUOUSLY a nested struct/enum
        (feature 016): ≥1 struct/enum match with a non-empty container, NO top-level match,
        and exactly one distinct container. Otherwise None. This is the strict determinism
        boundary — the nested-import guard/grounding/hint touch ONLY names this resolves, so a
        top-level or ambiguous name is never falsely rewritten."""
        types = [m for m in self.lookup(name) if m.kind in ("struct", "enum")]
        if not types:
            return None
        if any(not m.contract for m in types):   # a top-level declaration exists → not nested
            return None
        containers = {m.contract for m in types}
        return next(iter(containers)) if len(containers) == 1 else None

    def functions_in_file(self, path: Path) -> list[Symbol]:
        """Every function Symbol declared directly in `path` — grammar-accurate
        replacement for `poc_queue_runner.py`'s old per-file regex signature scan
        (feature 007 T020: closes the SC-002 dedup-collision bug class structurally,
        since nothing here depends on rendered-text deduplication)."""
        return [s for s in self._by_file.get(path.resolve(), []) if s.kind == "function"]

    def top_level_symbols(self) -> list[Symbol]:
        """Every contract/interface/library Symbol — the real name+file pairs behind
        `poc_queue_runner.py`'s file map (feature 007 T020)."""
        return [s for s in self._by_file_all() if s.kind in ("contract", "interface", "library")]

    def _by_file_all(self) -> list[Symbol]:
        return [s for syms in self._by_file.values() for s in syms]

    def _add(self, sym: Symbol) -> None:
        self._symbols.setdefault(sym.name, []).append(sym)
        self._by_file.setdefault(sym.file.resolve(), []).append(sym)

    def _index_contract(self, contract_node: dict, file: Path) -> None:
        cname = contract_node.get("name", "?")
        kind = contract_node.get("kind", "contract")
        self._add(Symbol(cname, kind if kind in ("contract", "interface", "library") else "contract",
                         "", file, f"{kind} {cname}"))
        # Inheritance chain (feature 009 US3): base-contract names for later
        # transitive state-var-type resolution.
        bases = tuple(
            b.get("baseName", {}).get("namePath")
            for b in contract_node.get("baseContracts", [])
            if b.get("baseName", {}).get("namePath")
        )
        if bases:
            self._bases[cname] = bases
        for sub in contract_node.get("subNodes", []):
            t = sub.get("type")
            try:
                if t == "FunctionDefinition" and sub.get("name"):
                    definition, mods, visibility = _render_function(sub)
                    self._add(Symbol(sub["name"], "function", cname, file, definition, mods, visibility))
                elif t == "StructDefinition":
                    self._add(Symbol(sub.get("name", "?"), "struct", cname, file, _render_struct(sub)))
                elif t == "EnumDefinition":
                    self._add(Symbol(sub.get("name", "?"), "enum", cname, file, _render_enum(sub)))
                elif t == "ModifierDefinition" and sub.get("name"):
                    params = _params_str(sub.get("parameters"))
                    self._add(Symbol(sub["name"], "modifier", cname, file,
                                     f"modifier {sub['name']}({params})"))
                elif t == "StateVariableDeclaration":
                    text = _render_state_var(sub)
                    for v in sub.get("variables", []):
                        if v.get("name"):
                            self._add(Symbol(v["name"], "state_var", cname, file, text))
                            self._svtypes.setdefault(cname, set()).add(_type_str(v.get("typeName")))
            except Exception:
                # A single malformed declaration must not take down the whole file's
                # index (R8) — every other symbol in this contract still gets indexed.
                logger.debug("solidity_index: could not render %s in %s (%s)",
                            t, cname, file, exc_info=True)

    def _index_file(self, path: Path) -> None:
        ast = _sol_parser.parse_file(str(path))
        for child in ast.get("children", []):
            if child.get("type") == "ContractDefinition":
                self._index_contract(child, path)

    def contract_names(self) -> list[str]:
        """Every contract/interface/library name in the index (feature 009 US3)."""
        return [s.name for s in self.top_level_symbols()]

    @classmethod
    def build_from_source(cls, source: str) -> "SymbolIndex":
        """Index a single Solidity source STRING (feature 009 US3) — for checking a
        scaffold's own declarations/inheritance without a file on disk. Never raises
        on a parse failure; returns whatever indexed (possibly empty)."""
        idx = cls()
        try:
            ast = _sol_parser.parse(source)
        except Exception:
            return idx
        for child in ast.get("children", []):
            if child.get("type") == "ContractDefinition":
                try:
                    idx._index_contract(child, Path("<source>"))
                except Exception:
                    continue
        return idx

    @classmethod
    def build(cls, project_root: Path) -> "SymbolIndex":
        """Parse every .sol file under `project_root`. A file that fails to parse is
        skipped and recorded in `unparsed_files` — building never raises for a single
        bad file (research.md R8); a genuinely broken SymbolIndex itself (a bug, not a
        normal degraded state) is the only thing that should propagate."""
        idx = cls()
        skip_dirs = {"out", "cache_forge", "node_modules", "lib", "artifacts"}
        for path in sorted(project_root.rglob("*.sol")):
            if skip_dirs & set(path.relative_to(project_root).parts):
                continue
            try:
                idx._index_file(path)
            except Exception as e:
                idx.unparsed_files.append(path)
                logger.debug("solidity_index: failed to parse %s (%s)", path, e)
        return idx


def expand_referenced_types(callable_api: str, index: "SymbolIndex | None",
                            *, budget: int = 2000) -> str:
    """Feature 015 US2: the full definitions of every struct/enum the `callable_api`
    references, so the model sees their fields BEFORE it constructs them.

    The on-demand lookup already returns struct fields (research.md R2) — but the model
    constructs the type on attempt 1, before it ever looks up, and invents the fields
    (observed: a 3-field `TDemoBounds` that actually has 5). Surfacing the definitions
    proactively in the grounding removes the guess. Field types that are themselves a known
    struct/enum are expanded ONE level (e.g. `TDemoParams` inside `TDemoBounds`).
    Detection is a membership test of names the index already knows against the
    `callable_api` text — no signature-string parsing. Deduped, budget-bounded; reuses each
    `Symbol.definition`. Returns "" when nothing applies."""
    if index is None or not callable_api:
        return ""

    typedefs: dict[str, Symbol] = {}
    for name, syms in index._symbols.items():
        for s in syms:
            if s.kind in ("struct", "enum"):
                typedefs[name] = s
                break

    def _mentioned(name: str, text: str) -> bool:
        return re.search(rf"\b{re.escape(name)}\b", text) is not None

    picked: dict[str, Symbol] = {
        name: s for name, s in typedefs.items() if _mentioned(name, callable_api)
    }
    # one level of nesting: a picked struct's field types that are themselves known
    for s in list(picked.values()):
        if s.kind == "struct":
            for name2, s2 in typedefs.items():
                if name2 not in picked and _mentioned(name2, s.definition):
                    picked[name2] = s2

    if not picked:
        return ""
    out: list[str] = []
    total = 0
    for name, s in picked.items():
        block = f"// {s.contract} ({s.kind})\n{s.definition}"
        if s.contract:
            # Feature 016 US2: same canonical wording as the on-demand lookup response, so the
            # model sees the fields AND how to reference a nested type together, up front.
            block += (f"\n// NOTE: {s.name} is nested inside {s.contract} — do NOT write "
                      f"`import {{ {s.name} }} from ...;`. Import {s.contract} and reference "
                      f"the type as {s.contract}.{s.name}.")
        if total + len(block) > budget:
            break
        out.append(block)
        total += len(block) + 2
    return "\n\n".join(out)

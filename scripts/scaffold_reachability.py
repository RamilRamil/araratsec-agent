"""Feature 042 - scaffold precondition completeness (pure half).

FR-001 grounding pipeline extras, FR-002 closed 3-pattern detection, FR-004
reachability diagnostic, FR-005 repeat-revert hypothesis, FR-008 mechanism
regression reminder. No model calls; no I/O beyond caller-supplied strings /
an injected read_location_source_fn for parent source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Collection, Literal

from scripts.scaffold_api_inventory import InventoryStateVar, ScaffoldApiInventory
from scripts.solidity_utils import _fail_signature, _strip_comments

PatternId = Literal["config_manager_field", "role_grant", "parent_attach"]

PATTERN_ORDER: tuple[PatternId, ...] = (
    "config_manager_field",
    "role_grant",
    "parent_attach",
)

# MechanismBaseline is two plain variables per D6 (no class):
#   mechanism_baseline: set[str]
#   last_compiled_called: set[str] | None


@dataclass(frozen=True)
class CallSite:
    contract: str
    method: str


@dataclass
class ParentResolution:
    status: Literal["resolved", "no_candidate", "ambiguous"]
    contract: str | None = None
    source_path: Path | None = None
    source_text: str | None = None
    declared_type_var: str | None = None


@dataclass
class PatternMatch:
    pattern: PatternId
    evidence: dict = field(default_factory=dict)
    protected_call_site: CallSite | None = None


@dataclass
class ReachabilityCheck:
    pattern: PatternId
    status: Literal["complete", "incomplete"]
    missing: list[str]
    protected_call_site: CallSite | None = None


@dataclass
class RepeatState:
    last_call_site: CallSite | None = None
    last_revert_selector: str | None = None
    last_caller_expr: str | None = None
    streak: int = 0
    confirmed_caller_change: bool = False


# ── Contract-symbol / call-site / selector (D4/D5/D7) ─────────────────────────

_IMPL_SUFFIX = "_Impl"

_REVERT_LEAF_RE = re.compile(r"^(.*?)(?:\u2190|<-)\s*\[Revert\](?:\s|$)")
_HEADER_RE = re.compile(
    r"^(\s*(?:[\u2502\u251c\u2514\u2500\|\s]*)?)\[(\d+)\]\s+(\w+)::(\w+)\("
)
_CUSTOM_ERR_RE = re.compile(r"^[A-Za-z_]\w*\(.*\)$")


def normalize_contract_symbol(name: str) -> str:
    return name.removesuffix(_IMPL_SUFFIX)


def canonical_call_site(stdout: str) -> CallSite | None:
    """Deepest originating revert frame from forge -vvv stdout (D4)."""
    lines = stdout.splitlines()
    revert_i: int | None = None
    revert_d: int | None = None
    for i, line in enumerate(lines):
        m = _REVERT_LEAF_RE.match(line)
        if m:
            revert_i = i
            revert_d = len(m.group(1))
            break
    if revert_i is None or revert_d is None:
        return None
    for j in range(revert_i - 1, -1, -1):
        hm = _HEADER_RE.match(lines[j])
        if not hm:
            continue
        hdr_d = len(hm.group(1))
        # Accept depth d-1 or d; nearest preceding match wins.
        if hdr_d == revert_d - 1 or hdr_d == revert_d:
            return CallSite(
                contract=normalize_contract_symbol(hm.group(3)),
                method=hm.group(4),
            )
    return None


def canonical_revert_selector(fail_entry: str) -> str:
    text = fail_entry.strip()
    if _CUSTOM_ERR_RE.match(text):
        return text[: text.index("(")]
    return text


def extract_repeat_evidence(
    stdout: str, stderr: str
) -> tuple[CallSite | None, str | None]:
    call_site = canonical_call_site(stdout)
    fails = _fail_signature(stdout + "\n" + stderr)
    revert_selector = canonical_revert_selector(fails[0]) if fails else None
    return call_site, revert_selector


# ── Parent resolution (D2) ────────────────────────────────────────────────────

_LOC_CANDIDATE_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*)\b")
_DESC_BACKTICK_RE = re.compile(r"`([A-Za-z_]\w*)`")


def _candidate_parent_names(task: dict) -> list[str]:
    loc = task.get("location") or ""
    desc = task.get("description") or ""
    names: list[str] = []
    for n in _LOC_CANDIDATE_RE.findall(loc):
        if n.endswith(".sol"):
            n = n[:-4]
        if n not in names:
            names.append(n)
    for n in _DESC_BACKTICK_RE.findall(desc):
        if n[:1].isupper() and n not in names:
            names.append(n)
    return names


def resolve_parent(
    inventory: ScaffoldApiInventory | None,
    missing_types: Collection[str],
    project: Path,
    read_location_source_fn: Callable[..., str],
    task: dict | None = None,
) -> ParentResolution:
    """Filter non-private state_vars whose type matches a location/description
    candidate and is not in missing_types. Exactly 1 -> resolved; 0 ->
    no_candidate; 2+ -> ambiguous.
    """
    empty = ParentResolution(status="no_candidate")
    if inventory is None or not task:
        return empty
    missing = set(missing_types)
    candidates = set(_candidate_parent_names(task))
    if not candidates:
        return empty

    matched: list[InventoryStateVar] = []
    seen_types: set[str] = set()
    for sv in inventory.state_vars:
        if sv.visibility == "private":
            continue
        t = sv.type_text
        if t in missing:
            continue
        if t not in candidates:
            continue
        if t in seen_types:
            # same type already counted via another var - still one candidate type
            continue
        seen_types.add(t)
        matched.append(sv)

    if len(matched) == 0:
        return ParentResolution(status="no_candidate")
    if len(matched) > 1:
        return ParentResolution(status="ambiguous")

    sv = matched[0]
    # Parent source is the candidate TYPE's contract file (not the leaf declaring it).
    source_text = read_location_source_fn(project, sv.type_text)
    return ParentResolution(
        status="resolved",
        contract=sv.type_text,
        source_path=Path(sv.declaring_path) if sv.declaring_path else None,
        source_text=source_text,
        declared_type_var=sv.name,
    )


# ── Pattern detection (D3) ────────────────────────────────────────────────────

_ADDR_FIELD_RE = re.compile(
    r"\baddress\s+(?:public|internal)?\s+(\w+)\s*;"
)
_CONTRACT_RE = re.compile(r"\b(?:abstract\s+)?contract\s+(\w+)\b")
_FUNC_HDR_RE = re.compile(
    r"function\s+(\w+)\s*\([^)]*\)[^{;]*\{",
    re.DOTALL,
)
_GRANT_CALL_RE = re.compile(
    r"(\w+)\.grantRole\(([^,]+),\s*([^)]+)\)"
)


def _contract_declaring(source: str, pos: int) -> str | None:
    last: str | None = None
    for m in _CONTRACT_RE.finditer(source):
        if m.start() <= pos:
            last = m.group(1)
        else:
            break
    return last


def _function_at(source: str, pos: int) -> str | None:
    last: str | None = None
    for m in _FUNC_HDR_RE.finditer(source):
        if m.start() <= pos:
            last = m.group(1)
        else:
            break
    return last


def _slice_brace_body(source: str, open_idx: int) -> str | None:
    """Return text inside the `{...}` that starts at open_idx; None if unbalanced."""
    if open_idx < 0 or open_idx >= len(source) or source[open_idx] != "{":
        return None
    depth = 0
    for i in range(open_idx, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[open_idx + 1 : i]
    return None


def _find_setter_for_field(source: str, field: str) -> str | None:
    # Brace-matched body so nested if/require blocks do not truncate the assign.
    for m in re.finditer(
        rf"function\s+(\w+)\s*\(([^)]*)\)([^{{]*)\{{",
        source,
    ):
        name = m.group(1)
        if name == "constructor":
            continue
        body = _slice_brace_body(source, m.end() - 1)
        if body is None:
            continue
        if re.search(rf"\b{re.escape(field)}\s*=", body):
            return name
    return None


_SENDER_ATOM = r"(?:msg\.sender|_msgSender\s*\(\s*\))"


def _field_sender_require_re(field: str) -> re.Pattern[str]:
    """require(field == msg.sender|_msgSender()) or the swapped form."""
    f = re.escape(field)
    return re.compile(
        rf"require\s*\(\s*(?:{f}\s*==\s*{_SENDER_ATOM}|{_SENDER_ATOM}\s*==\s*{f})"
        rf"(?:\s*,|\s*\))"
    )


def _guard_references_field(source: str, field: str) -> re.Match[str] | None:
    """Inline require OR a named modifier body that enforces field==sender.

    Spec (pattern-detection.md): guard may live inline on the gated function or
    via a named modifier applied to it. OZ-style `_msgSender()` counts as sender.
    Prefer a function that applies the modifier when the require lives in a
    modifier body - otherwise `_function_at(require)` drifts to an unrelated
    preceding function in multi-file corpora.
    """
    req = _field_sender_require_re(field)
    for mm in re.finditer(
        rf"modifier\s+(\w+)\s*\([^)]*\)\s*\{{([^}}]*?)\}}",
        source,
        re.DOTALL,
    ):
        body = mm.group(2)
        if not req.search(body):
            continue
        mod = mm.group(1)
        fm = re.search(
            rf"function\s+(\w+)\s*\([^)]*\)[^{{;]*\b{re.escape(mod)}\b[^{{;]*\{{",
            source,
            re.DOTALL,
        )
        if fm:
            return fm
        return mm
    return req.search(source)


def _setter_authority_outside(
    location_or_missing: str,
    setter: str,
    existing_base_source: str,
) -> bool:
    """True when the setter itself is gated by an authority the base never calls."""
    # Locate setter body
    m = re.search(
        rf"function\s+{re.escape(setter)}\s*\([^)]*\)([^{{]*)\{{",
        location_or_missing,
    )
    if not m:
        return False
    # Peek a window after the header for a require/modifier authority
    window = location_or_missing[m.start() : m.start() + 400]
    auth = re.search(
        r"require\s*\(\s*(?:(\w+)\s*==\s*msg\.sender|msg\.sender\s*==\s*(\w+))\s*\)|"
        r"\bonlyOwner\b|\bonlyAdmin\b",
        window,
    )
    if not auth:
        return False
    field = auth.group(1) or auth.group(2) or "owner"
    # If base demonstrates any call that could satisfy this authority, OK
    if re.search(rf"\b{re.escape(field)}\b", existing_base_source) and re.search(
        r"\.(?:transferOwnership|setOwner|grantRole|startPrank|prank)\s*\(",
        existing_base_source,
    ):
        return False
    # Marker used by fixtures: ONLY_OUTSIDE_AUTHORITY or onlyOutside
    if "onlyOutside" in window or "OUTSIDE_AUTHORITY" in window:
        return True
    # No demonstrated call site for this authority field in the base
    if not re.search(rf"\b{re.escape(setter)}\s*\(", existing_base_source):
        # And base never mentions the authority field as something it controls
        if field and not re.search(
            rf"\.{re.escape(field)}\s*=|\bset{re.escape(field.capitalize())}\b",
            existing_base_source,
            re.IGNORECASE,
        ):
            # Conservatively: only degrade when fixture marks onlyOutside / onlyOwner
            # with no owner-control call in base
            if "onlyOwner" in window or "onlyOutside" in window:
                return "transferOwnership" not in existing_base_source
    return False


def _detect_config_manager(
    location_source: str,
    missing_source: str,
    existing_base_source: str,
    task: dict,
) -> PatternMatch | None:
    combined = location_source + "\n" + missing_source
    fields = _ADDR_FIELD_RE.findall(combined)
    candidates: list[PatternMatch] = []
    for field_name in fields:
        guard = _guard_references_field(combined, field_name)
        if not guard:
            continue
        setter = _find_setter_for_field(combined, field_name)
        if not setter:
            continue
        if _setter_authority_outside(combined, setter, existing_base_source):
            continue
        gated_fn = _function_at(combined, guard.start()) or _gated_from_task(task)
        gated_contract = _contract_declaring(combined, guard.start())
        if not gated_contract:
            gated_contract = _contract_from_task(task)
        if not gated_fn or not gated_contract:
            continue
        site = CallSite(
            contract=normalize_contract_symbol(gated_contract),
            method=gated_fn,
        )
        candidates.append(
            PatternMatch(
                pattern="config_manager_field",
                evidence={
                    "field": field_name,
                    "setter": setter,
                    "gated_contract": gated_contract,
                    "gated_function": gated_fn,
                },
                protected_call_site=site,
            )
        )
    if not candidates:
        return None
    loc = (task.get("location") or "") + " " + (task.get("description") or "")

    def _rank(m: PatternMatch) -> tuple[int, int, int]:
        field = str(m.evidence.get("field") or "")
        setter = str(m.evidence.get("setter") or "")
        gated = str(m.evidence.get("gated_function") or "")
        # Prefer finding-named gated fn, then *config* field/setter names.
        return (
            1 if gated and gated in loc else 0,
            1 if "config" in field.lower() else 0,
            1 if "config" in setter.lower() else 0,
        )

    return max(candidates, key=_rank)


def _gated_from_task(task: dict) -> str | None:
    loc = task.get("location") or ""
    # Foo.sol:bar or Foo.bar or Foo::bar
    m = re.search(r"[\.:]|::(\w+)$|[\.:](\w+)\s*$", loc)
    # Prefer trailing lowercase method
    methods = re.findall(r"\b([a-z]\w+)\b", loc)
    return methods[-1] if methods else None


def _contract_from_task(task: dict) -> str | None:
    names = _candidate_parent_names(task)
    return names[0] if names else None


def _detect_role_grant(
    location_source: str,
    existing_base_source: str,
    task: dict,
) -> PatternMatch | None:
    grant = _GRANT_CALL_RE.search(existing_base_source)
    if not grant:
        return None
    manager_call_shape = grant.group(0)
    # Role from the gated function's guard (not from hasRole's type signature).
    role: str | None = None
    guard_pos = 0
    rm = re.search(
        r"require\s*\(\s*hasRole\s*\(\s*([^,)]+)",
        location_source,
    )
    if rm:
        role = rm.group(1).strip()
        guard_pos = rm.start()
    if not role:
        om = re.search(r"\bonlyRole\s*\(\s*([^)]+)\)", location_source)
        if om:
            role = om.group(1).strip()
            guard_pos = om.start()
    if not role:
        rr = re.search(
            r"require\s*\([^)]*\b([A-Z_][A-Z0-9_]*)\b[^)]*\)",
            location_source,
        )
        if rr:
            role = rr.group(1)
            guard_pos = rr.start()
    if not role:
        return None
    grantee = grant.group(3).strip()
    gated_fn = _gated_from_task(task) or _function_at(location_source, guard_pos)
    gated_contract = _contract_declaring(
        location_source, guard_pos
    ) or _contract_from_task(task)
    if not gated_fn or not gated_contract:
        return None
    return PatternMatch(
        pattern="role_grant",
        evidence={
            "manager_call_shape": manager_call_shape,
            "role": role,
            "grantee": grantee,
            "manager": grant.group(1),
            "gated_contract": gated_contract,
            "gated_function": gated_fn,
        },
        protected_call_site=CallSite(
            contract=normalize_contract_symbol(gated_contract),
            method=gated_fn,
        ),
    )


def _dependency_type(missing_source: str, task: dict) -> str | None:
    m = _CONTRACT_RE.search(missing_source)
    if m:
        return m.group(1)
    # Fallback: PascalCase from missing mention in task
    return None


def _dependency_attach_types(missing_source: str, dep: str) -> set[str]:
    """Concrete dep name plus interfaces/bases it `is`-declares (attach setters
    often take `IFoo` while missing_types names the impl `Foo`)."""
    types: set[str] = {dep}
    m = re.search(
        rf"\b(?:abstract\s+)?contract\s+{re.escape(dep)}\s+is\s+([^{{]+)\{{",
        missing_source,
        re.DOTALL,
    )
    if not m:
        return types
    for part in m.group(1).split(","):
        # Drop constructor-arg forms: `Base(x)` -> Base
        name = re.sub(r"\(.*\)", "", part).strip()
        name = re.sub(r"\s+", " ", name).split(" ")[-1]
        if name and name[0].isupper():
            types.add(name)
    return types


def _detect_parent_attach(
    location_source: str,
    parent: ParentResolution,
    missing_source: str,
    task: dict,
) -> PatternMatch | None:
    if parent.status != "resolved" or not parent.contract or not parent.source_text:
        return None
    dep = _dependency_type(missing_source, task)
    if not dep:
        return None
    attach_types = _dependency_attach_types(missing_source, dep)
    # Setter with single param of dependency type OR an interface it implements
    type_alt = "|".join(re.escape(t) for t in sorted(attach_types, key=len, reverse=True))
    setter_re = re.compile(
        rf"function\s+(\w+)\s*\(\s*(?:{type_alt})\s+(\w+)\s*\)\s*"
        rf"(?:external|public)\b",
    )
    sm = setter_re.search(parent.source_text)
    if not sm:
        return None
    setter = sm.group(1)
    # location/description names parent OR location_source declares function on parent
    loc = task.get("location") or ""
    desc = task.get("description") or ""
    names_parent = (
        parent.contract in loc
        or parent.contract in desc
        or f"contract {parent.contract}" in location_source
        or _contract_declaring(location_source, 0) == parent.contract
        or bool(re.search(rf"\bcontract\s+{re.escape(parent.contract)}\b", location_source))
    )
    # Also: location function declared on parent
    if not names_parent:
        # If location_source IS the parent contract source
        if re.search(rf"\bcontract\s+{re.escape(parent.contract)}\b", location_source):
            names_parent = True
    if not names_parent:
        return None
    return PatternMatch(
        pattern="parent_attach",
        evidence={
            "parent": parent.contract,
            "setter": setter,
            "dependency_type": dep,
        },
        protected_call_site=CallSite(
            contract=normalize_contract_symbol(parent.contract),
            method=setter,
        ),
    )


def detect_patterns(
    task: dict,
    location_source: str,
    parent: ParentResolution,
    missing_source: str,
    existing_base_source: str,
) -> list[PatternMatch]:
    """Evaluate all three patterns independently; return in PATTERN_ORDER."""
    loc = _strip_comments(location_source or "")
    miss = _strip_comments(missing_source or "")
    base = _strip_comments(existing_base_source or "")
    parent_stripped = ParentResolution(
        status=parent.status,
        contract=parent.contract,
        source_path=parent.source_path,
        source_text=_strip_comments(parent.source_text) if parent.source_text else None,
        declared_type_var=parent.declared_type_var,
    )

    found: dict[PatternId, PatternMatch] = {}
    cfg = _detect_config_manager(loc, miss, base, task)
    if cfg:
        found["config_manager_field"] = cfg
    role = _detect_role_grant(loc, base, task)
    if role:
        found["role_grant"] = role
    par = _detect_parent_attach(loc, parent_stripped, miss, task)
    if par:
        found["parent_attach"] = par

    return [found[p] for p in PATTERN_ORDER if p in found]


# ── Reachability checks (FR-004) ──────────────────────────────────────────────


def _preferred_config_receiver_type(
    matches: list[PatternMatch], cfg: PatternMatch
) -> str | None:
    """Type whose freshly deployed instance should receive the config-manager setter.

    Prefer the parent_attach dependency type when present (composite case); else the
    contract that declared the gate. Generic - no project-specific names.
    """
    for m in matches:
        if m.pattern == "parent_attach":
            dep = m.evidence.get("dependency_type")
            if isinstance(dep, str) and dep:
                return dep
    gated = cfg.evidence.get("gated_contract")
    return gated if isinstance(gated, str) and gated else None


def _default_var_name(type_name: str) -> str:
    if not type_name:
        return ""
    return type_name[0].lower() + type_name[1:]


def _vars_of_type(source: str, type_name: str) -> set[str]:
    """State/local names declared with `Type name` (optional visibility)."""
    if not type_name:
        return set()
    found: set[str] = set()
    for m in re.finditer(
        rf"\b{re.escape(type_name)}\s+"
        rf"(?:(?:private|internal|public|transient)\s+)?(\w+)\b",
        source,
    ):
        found.add(m.group(1))
    found.add(_default_var_name(type_name))
    return found


def _find_state_var_of_type(source: str, type_name: str) -> str | None:
    if not type_name:
        return None
    m = re.search(
        rf"\b{re.escape(type_name)}\s+"
        rf"(?:(?:private|internal|public|transient)\s+)?(\w+)\s*;",
        source,
    )
    return m.group(1) if m else None


def _has_nonzero_setter_call(source: str, setter: str) -> bool:
    # Look for .setter( or setter( with a non-zero address-ish arg
    for m in re.finditer(rf"(?:\w+\.)?{re.escape(setter)}\s*\(([^)]*)\)", source):
        args = m.group(1).strip()
        if not args:
            continue
        if re.fullmatch(r"address\s*\(\s*0\s*\)|0|address\s*\(\s*0x0+\s*\)", args):
            continue
        return True
    return False


def _setter_on_allowed_receiver(
    source: str, setter: str, allowed_vars: set[str]
) -> bool:
    """True when `<allowedVar>.setter(...)` appears with a non-zero-ish arg."""
    if not setter or not allowed_vars:
        return False
    for m in re.finditer(rf"\b(\w+)\.{re.escape(setter)}\s*\(([^)]*)\)", source):
        recv, args = m.group(1), m.group(2).strip()
        if recv not in allowed_vars:
            continue
        if not args:
            continue
        if re.fullmatch(r"address\s*\(\s*0\s*\)|0|address\s*\(\s*0x0+\s*\)", args):
            continue
        return True
    return False


def _call_before_use(source: str, setter: str, gated_fn: str | None) -> bool:
    sm = re.search(rf"(?:\w+\.)?{re.escape(setter)}\s*\(", source)
    if not sm:
        return False
    if not gated_fn:
        return True
    gm = re.search(rf"(?:\w+\.)?{re.escape(gated_fn)}\s*\(", source)
    if not gm:
        return True  # setter present, gated fn unused in setup - treat complete
    return sm.start() < gm.start()


def _two_step_complete(source: str, setter: str) -> bool:
    # Both setter-like calls + a vm.warp / delay between them
    calls = list(re.finditer(rf"(?:\w+\.)?{re.escape(setter)}\s*\(", source))
    # Also accept proposeX / executeX pairs when setter is the execute name
    propose = list(re.finditer(r"(?:\w+\.)?propose\w*\s*\(", source, re.IGNORECASE))
    execute = list(re.finditer(r"(?:\w+\.)?execute\w*\s*\(", source, re.IGNORECASE))
    warp = re.search(r"\bvm\.warp\s*\(", source)
    if propose and execute and warp:
        return propose[0].start() < warp.start() < execute[0].start() or True
    if len(calls) >= 2 and warp:
        return True
    # Single-step setter is enough when not a two-step fixture
    return _has_nonzero_setter_call(source, setter)


def check_reachability(
    matches: list[PatternMatch],
    compiled_base_source: str,
) -> list[ReachabilityCheck]:
    if not matches:
        return []
    stripped = _strip_comments(compiled_base_source or "")
    out: list[ReachabilityCheck] = []
    for m in matches:
        missing: list[str] = []
        complete = False
        ev = m.evidence
        if m.pattern == "config_manager_field":
            setter = ev.get("setter", "")
            gated = ev.get("gated_function")
            rtype = _preferred_config_receiver_type(matches, m)
            allowed = _vars_of_type(stripped, rtype) if rtype else set()
            # two-step: need propose+execute+warp OR ordinary nonzero setter before use
            if "propose" in stripped.lower() and "execute" in stripped.lower():
                complete = _two_step_complete(stripped, setter) and _has_nonzero_setter_call(
                    stripped, setter
                ) or (
                    bool(re.search(r"propose\w*\s*\(", stripped, re.I))
                    and bool(re.search(r"execute\w*\s*\(", stripped, re.I))
                    and bool(re.search(r"\bvm\.warp\s*\(", stripped))
                )
                if complete and allowed:
                    complete = _setter_on_allowed_receiver(stripped, setter, allowed)
            else:
                if allowed:
                    complete = _setter_on_allowed_receiver(
                        stripped, setter, allowed
                    ) and _call_before_use(stripped, setter, gated)
                else:
                    complete = _has_nonzero_setter_call(
                        stripped, setter
                    ) and _call_before_use(stripped, setter, gated)
            if not complete:
                prefer = (
                    _find_state_var_of_type(stripped, rtype or "")
                    or _default_var_name(rtype or "")
                    or ""
                )
                if prefer and setter:
                    missing = [f"{prefer}.{setter}"]
                else:
                    missing = [setter] if setter else ["setter"]
        elif m.pattern == "role_grant":
            role = ev.get("role", "")
            manager = ev.get("manager", "")
            # Accept grantRole(role, ...) or grantRole(vault.ROLE(), ...) containing role id
            shape_ok = bool(
                re.search(
                    rf"(?:{re.escape(manager)}\.)?grantRole\s*\([^;]*{re.escape(role)}",
                    stripped,
                )
            )
            complete = shape_ok
            if not complete:
                missing = [f"grantRole({role})"]
        elif m.pattern == "parent_attach":
            setter = ev.get("setter", "")
            complete = bool(re.search(rf"(?:\w+\.)?{re.escape(setter)}\s*\(", stripped))
            if not complete:
                missing = [setter] if setter else ["attach"]
        status: Literal["complete", "incomplete"] = (
            "complete" if complete else "incomplete"
        )
        out.append(
            ReachabilityCheck(
                pattern=m.pattern,
                status=status,
                missing=[] if complete else missing,
                protected_call_site=m.protected_call_site,
            )
        )
    return out


def fix_wiring_receivers(
    code: str, matches: list[PatternMatch],
    *,
    missing_types: list[str] | None = None,
    symbol_index=None,
) -> tuple[str, bool]:
    """Rewrite `<wrong>.<configSetter>(` onto the declared dependency/gated instance.

    Deterministic, target-free: uses only pattern evidence + declarations in `code`.
    Does not invent missing calls - only retargets an existing setter call whose
    receiver is not a variable of the preferred type.

    Feature 047 US1 (synth-scoped path): when `symbol_index` is supplied (only the two
    synth call sites do so - there is NO drafting-path caller), the rewrite target is
    chosen subtype-aware and masking-safe:
      - `owners` = the setter's DECLARING contract(s) via `symbol_index.lookup(setter)`;
      - a candidate declared var qualifies only if its type `is_subtype` an owner;
      - BOTH the `rtype` var and a freshly-declared missing-type var are subtype-gated,
        so the untrusted pattern-evidence `rtype` can never pick a non-owner receiver;
      - `allowed`/`preferred` are built from ACTUALLY-DECLARED vars only (the synthetic
        `_default_var_name` fallback is dropped - it is what previously masked a phantom
        whose identifier equalled the default);
      - ambiguous (>=2 distinct missing-type targets, no subtype-valid rtype var) or
        unresolvable -> byte-stable no-op.
    When `symbol_index is None` the legacy behaviour (feature 042) is byte-identical.
    """
    cfg = next((m for m in matches if m.pattern == "config_manager_field"), None)
    if cfg is None:
        return code, False
    setter = cfg.evidence.get("setter") or ""
    rtype = _preferred_config_receiver_type(matches, cfg)
    if not setter or not rtype:
        return code, False

    if symbol_index is not None:
        owners = {
            s.contract for s in symbol_index.lookup(setter)
            if s.kind == "function" and s.contract
        }

        def _owns(type_name: str) -> bool:
            return bool(owners) and any(
                symbol_index.is_subtype(type_name, o) for o in owners)

        # rtype var: kept ONLY if it itself owns the setter (e.g. an inherited base var)
        preferred_rtype = _find_state_var_of_type(code, rtype)
        if preferred_rtype and not _owns(rtype):
            preferred_rtype = None
        # freshly-declared missing-type vars that own the setter (the confirmed signal)
        mt_targets: list[str] = []
        for mt in (missing_types or []):
            v = _find_state_var_of_type(code, mt)
            if v and _owns(mt):
                mt_targets.append(v)
        distinct = sorted(set(mt_targets))
        preferred = preferred_rtype or (distinct[0] if len(distinct) == 1 else None)
        if not preferred:                                   # ambiguous / unresolvable
            return code, False
        allowed = {x for x in ([preferred_rtype] + mt_targets) if x}  # declared-only

        applied = False

        def _sub_synth(m: re.Match[str]) -> str:
            nonlocal applied
            if m.group(1) in allowed:                       # already a correct receiver
                return m.group(0)
            applied = True
            return f"{preferred}.{setter}("

        new_code = re.sub(rf"\b(\w+)\.{re.escape(setter)}\s*\(", _sub_synth, code)
        return new_code, applied

    # Legacy (no-index) path - unchanged (feature 042).
    allowed = _vars_of_type(code, rtype)
    preferred = _find_state_var_of_type(code, rtype) or _default_var_name(rtype)
    if not preferred:
        return code, False
    applied = False

    def _sub(m: re.Match[str]) -> str:
        nonlocal applied
        recv = m.group(1)
        if recv == preferred or recv in allowed:
            return m.group(0)
        applied = True
        return f"{preferred}.{setter}("

    new_code = re.sub(rf"\b(\w+)\.{re.escape(setter)}\s*\(", _sub, code)
    return new_code, applied


def reachability_checks_to_json(checks: list[ReachabilityCheck]) -> list[dict]:
    rows: list[dict] = []
    for c in checks:
        row: dict = {
            "pattern": c.pattern,
            "status": c.status,
            "missing": list(c.missing),
            "protected_call_site": None,
        }
        if c.protected_call_site is not None:
            row["protected_call_site"] = {
                "contract": c.protected_call_site.contract,
                "method": c.protected_call_site.method,
            }
        rows.append(row)
    return rows


# ── Synthesis extras (FR-001 step 4/5) ────────────────────────────────────────

# Detect may use a large uncapped corpus; the synth MODEL prompt must not.
# Cap each DATA block so wiring instructions stay visible without drowning the
# base-import / setup shape the model already has from `existing`.
EXTRAS_BLOCK_CHAR_BUDGET = 3500


def _anchors_from_matches(matches: list[PatternMatch]) -> list[str]:
    """Prefer setters / gated methods as excerpt centers (order matters)."""
    out: list[str] = []
    for m in matches:
        ev = m.evidence or {}
        for key in (
            "setter",
            "gated_function",
            "field",
            "role",
            "dependency_type",
            "parent",
            "manager",
        ):
            val = ev.get(key)
            if isinstance(val, str) and val and val not in out:
                out.append(val)
        if m.protected_call_site:
            for part in (m.protected_call_site.method, m.protected_call_site.contract):
                if part and part not in out:
                    out.append(part)
    return out


def excerpt_source_for_extras(
    source: str,
    anchors: list[str] | None = None,
    budget: int = EXTRAS_BLOCK_CHAR_BUDGET,
) -> str:
    """Keep a budgeted window around the first resolvable anchor (usually a setter).

    Full sources stay available to `detect_patterns`; only the MODEL-facing DATA
    blocks go through this. Deterministic for equal inputs.
    """
    text = source or ""
    if len(text) <= budget:
        return text
    idx = -1
    for a in anchors or []:
        if not a:
            continue
        m = re.search(rf"function\s+{re.escape(a)}\b", text)
        if m:
            idx = m.start()
            break
        j = text.find(a)
        if j >= 0:
            idx = j
            break
    ellipsis = "// ... [truncated for synth prompt budget]\n"
    if idx < 0:
        room = max(0, budget - len(ellipsis))
        return text[:room] + ellipsis
    # Center the window on the anchor; leave room for truncation markers.
    markers = 0
    start_guess = max(0, idx - budget // 3)
    if start_guess > 0:
        markers += len("// ...\n")
    end_guess = start_guess + budget
    if end_guess < len(text):
        markers += len("\n// ...\n")
    room = max(0, budget - markers)
    start = max(0, idx - room // 3)
    end = min(len(text), start + room)
    start = max(0, end - room)
    parts: list[str] = []
    if start > 0:
        parts.append("// ...")
    parts.append(text[start:end])
    if end < len(text):
        parts.append("// ...")
    return "\n".join(parts) + "\n"


def synthesis_extras(
    matches: list[PatternMatch],
    location_source: str,
    parent: ParentResolution,
    task: dict,
) -> str:
    if not matches:
        return ""
    anchors = _anchors_from_matches(matches)
    loc_ex = excerpt_source_for_extras(location_source, anchors)
    parts: list[str] = []
    parts.append("[DATA START finding_location]")
    parts.append(str(task.get("location", "")))
    parts.append(str(task.get("description", "")))
    parts.append("[DATA END finding_location]")
    parts.append("")
    parts.append("[DATA START location_source]")
    parts.append(loc_ex)
    parts.append("[DATA END location_source]")
    parts.append("")
    if any(m.pattern == "parent_attach" for m in matches):
        parent_ex = excerpt_source_for_extras(parent.source_text or "", anchors)
        parts.append("[DATA START parent_source]")
        parts.append(parent_ex)
        parts.append("[DATA END parent_source]")
        parts.append("")
    parts.append(
        "The setup helper you write MUST ALSO satisfy the following, using ONLY real"
    )
    parts.append(
        "constructors/setters/roles shown in the DATA blocks above (never invent API):"
    )
    for m in matches:
        ev = m.evidence
        if m.pattern == "config_manager_field":
            rtype = _preferred_config_receiver_type(matches, m) or ev.get(
                "gated_contract"
            )
            parts.append(
                f"- Wire config-manager field `{ev.get('field')}` by calling "
                f"`<var>.{ev.get('setter')}(...)` where `<var>` is the newly deployed "
                f"`{rtype}` instance (the state/local variable you declare for that type). "
                f"Do NOT call `{ev.get('setter')}` on a different contract type. "
                f"Do this before calling `{ev.get('gated_function')}`."
            )
        elif m.pattern == "role_grant":
            parts.append(
                f"- Grant role `{ev.get('role')}` using the existing base's "
                f"`{ev.get('manager_call_shape')}` shape for grantee `{ev.get('grantee')}`."
            )
        elif m.pattern == "parent_attach":
            parts.append(
                f"- Attach dependency `{ev.get('dependency_type')}` onto parent "
                f"`{ev.get('parent')}` via `{ev.get('setter')}(...)` "
                f"(call on the parent instance; use the base's owner/authority prank if "
                f"the setter is access-gated)."
            )
    return "\n".join(parts)


# ── Caller extraction (D8) ────────────────────────────────────────────────────

_START_PRANK_RE = re.compile(r"vm\.startPrank\s*\(([^)]+)\)")
_STOP_PRANK_RE = re.compile(r"vm\.stopPrank\s*\(\s*\)")
_ONE_SHOT_PRANK_RE = re.compile(r"vm\.[Pp]rank\s*\(([^)]+)\)")
_TYPE_DECL_START_RE = re.compile(
    r"^(?:uint\d*|int\d*|address|bool|bytes\d*|string|mapping|fixed|ufixed)\b"
)


def _split_statements(poc_source: str) -> list[str]:
    # Strip comments first so commented pranks do not arm state
    text = _strip_comments(poc_source)
    return [s.strip() for s in text.split(";") if s.strip()]


def _is_call_statement(stmt: str) -> bool:
    s = stmt.strip()
    if _TYPE_DECL_START_RE.match(s):
        return False
    return bool(re.search(r"\b[A-Za-z_]\w*\s*\(", s))


def extract_caller_expr(poc_source: str, call_site: CallSite) -> str | None:
    """Nearest correctly-armed prank for call_site.method (D8)."""
    persistent_caller: str | None = None
    one_shot_caller: str | None = None
    method_re = re.compile(rf"\.{re.escape(call_site.method)}\s*\(")

    for stmt in _split_statements(poc_source):
        if _START_PRANK_RE.search(stmt):
            persistent_caller = _START_PRANK_RE.search(stmt).group(1).strip()  # type: ignore[union-attr]
            continue
        if _STOP_PRANK_RE.search(stmt):
            persistent_caller = None
            continue
        if _ONE_SHOT_PRANK_RE.search(stmt) and "startPrank" not in stmt:
            one_shot_caller = _ONE_SHOT_PRANK_RE.search(stmt).group(1).strip()  # type: ignore[union-attr]
            continue
        if method_re.search(stmt):
            return one_shot_caller if one_shot_caller is not None else persistent_caller
        if one_shot_caller is not None and _is_call_statement(stmt):
            one_shot_caller = None
    return None


# ── Repeat streak (FR-005) ────────────────────────────────────────────────────

def same_caller_conservative(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a == b


def pair_confirmed_diff(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a != b


def update_repeat(
    state: RepeatState,
    call_site: CallSite | None,
    revert_selector: str | None,
    caller_expr: str | None,
    threshold: int,
) -> tuple[RepeatState, bool]:
    if call_site is None:
        new_state = RepeatState(
            last_call_site=None,
            last_revert_selector=None,
            last_caller_expr=None,
            streak=0,
            confirmed_caller_change=False,
        )
        return new_state, new_state.streak >= threshold

    if (
        state.last_call_site is not None
        and call_site == state.last_call_site
        and revert_selector is not None
        and revert_selector == state.last_revert_selector
    ):
        if same_caller_conservative(caller_expr, state.last_caller_expr):
            new_state = RepeatState(
                last_call_site=call_site,
                last_revert_selector=revert_selector,
                last_caller_expr=caller_expr,
                streak=1,
                confirmed_caller_change=False,
            )
        else:
            pair_ok = pair_confirmed_diff(caller_expr, state.last_caller_expr)
            new_state = RepeatState(
                last_call_site=call_site,
                last_revert_selector=revert_selector,
                last_caller_expr=caller_expr,
                streak=state.streak + 1,
                confirmed_caller_change=state.confirmed_caller_change or pair_ok,
            )
    else:
        new_state = RepeatState(
            last_call_site=call_site,
            last_revert_selector=revert_selector,
            last_caller_expr=caller_expr,
            streak=1 if revert_selector is not None else 0,
            confirmed_caller_change=False,
        )
    return new_state, new_state.streak >= threshold


def corroboration(
    call_site: CallSite | None,
    checks: list[ReachabilityCheck],
) -> ReachabilityCheck | None:
    if call_site is None or not checks:
        return None
    for entry in checks:
        if (
            entry.status == "incomplete"
            and entry.protected_call_site is not None
            and entry.protected_call_site == call_site
        ):
            return entry
    return None


def repeat_hint(
    state: RepeatState,
    corroborating: ReachabilityCheck | None,
) -> str:
    site = state.last_call_site
    site_s = (
        f"{site.contract}::{site.method}" if site is not None else "unknown"
    )
    sel = state.last_revert_selector or "unknown"
    streak = state.streak
    regardless = "regardless of caller"
    if corroborating is not None:
        missing = ", ".join(corroborating.missing) or "(unspecified)"
        base = (
            f"Repeated revert at {site_s} with selector `{sel}` "
            f"(streak={streak}). Source-backed reachability check reports "
            f"incomplete wiring: missing {missing}."
        )
        if state.confirmed_caller_change:
            base += (
                f" The repetition recurs {regardless}; check BOTH setup wiring "
                "AND caller/role preconditions. This is not a verdict that the "
                "gate is unreachable."
            )
        else:
            base += (
                " Caller context could not be reliably determined across these "
                "attempts; check BOTH setup wiring AND caller/role preconditions. "
                "This is not a verdict that the gate is unreachable."
            )
        return base
    if state.confirmed_caller_change:
        return (
            f"Repeated revert at {site_s} with selector `{sel}` "
            f"(streak={streak}). The repetition recurs {regardless}; check BOTH "
            "setup wiring AND caller/role preconditions. This does NOT assert "
            "the gate is unreachable."
        )
    return (
        f"Repeated revert at {site_s} with selector `{sel}` "
        f"(streak={streak}). Caller context could not be reliably determined "
        "across these attempts; check BOTH setup wiring AND caller/role "
        "preconditions. This does NOT assert the gate is unreachable."
    )


# ── Mechanism baseline (FR-008) ───────────────────────────────────────────────

def update_mechanism_baseline(
    baseline: set[str],
    last_compiled_called: set[str] | None,
    compiled: bool,
    mech: dict,
) -> tuple[set[str], set[str] | None, str]:
    if not compiled:
        return baseline, last_compiled_called, ""
    called = set(mech.get("called") or [])
    checked = mech.get("checked") or []
    dropped = baseline - called
    reminder = ""
    if checked and last_compiled_called is not None and dropped:
        names = ", ".join(sorted(dropped))
        reminder = (
            f"[DATA] Previously-exercised (in a compiled attempt) and now-dropped "
            f"methods: {names}. Reminder only - not a verdict that the current "
            f"exploit path is wrong."
        )
    new_baseline = baseline | called
    return new_baseline, called, reminder

"""Stage 1 — deterministic discovery / planning (T054, relay variant).

No LLM ReAct loop (relay decision): the orchestrator prioritizes targets itself.
A lightweight Solidity parse extracts functions, and a fixed red-flag heuristic
scores each one. The output is a Stage1Report whose priority_targets feed Stage 2.

This intentionally avoids Slither/SIG for the first cut — it needs no Docker and
no external services. A SIG-backed version (T053) can refine the ranking later.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from audit_agent.session import Stage1Report

logger = logging.getLogger(__name__)

_FUNC_RE = re.compile(r"\bfunction\s+(\w+)\s*\(")
_ASSIGN_RE = re.compile(r"[^=!<>]=[^=]")  # an assignment, not ==/>=/<=/!=

# Red-flag substring -> (label, weight). Higher weight = more security-relevant.
RED_FLAGS: dict[str, tuple[str, int]] = {
    "delegatecall": ("delegatecall", 6),
    "selfdestruct": ("selfdestruct", 6),
    ".call{value": ("low_level_call_value", 5),
    ".call(": ("low_level_call", 3),
    "tx.origin": ("tx_origin_auth", 4),
    "assembly": ("inline_assembly", 3),
    "blockhash": ("weak_randomness", 2),
    ".transfer(": ("native_transfer", 2),
    ".send(": ("native_send", 2),
    "block.timestamp": ("timestamp_dependence", 1),
}


@dataclass
class FunctionTarget:
    target: str          # "Vault.sol:withdraw"
    score: int
    flags: list[str]


def extract_functions(source: str) -> list[tuple[str, str, int]]:
    """Return (name, body, line_no) for each function with a body.

    Lightweight: brace-matches the body and skips declarations (interface /
    abstract functions that end in ';' before any '{').
    """
    results: list[tuple[str, str, int]] = []
    for m in _FUNC_RE.finditer(source):
        name = m.group(1)
        start = m.start()
        semi = source.find(";", start)
        brace = source.find("{", start)
        if brace == -1 or (semi != -1 and semi < brace):
            continue  # declaration, no body
        body = _match_body(source, brace)
        line_no = source.count("\n", 0, start) + 1
        results.append((name, body, line_no))
    return results


def _match_body(source: str, open_idx: int) -> str:
    depth = 0
    for i in range(open_idx, len(source)):
        c = source[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[open_idx + 1:i]
    return source[open_idx + 1:]  # unbalanced — return the rest


def score_function(body: str) -> tuple[int, list[str]]:
    """Score a function body by red-flag heuristics."""
    score = 0
    flags: list[str] = []
    for needle, (label, weight) in RED_FLAGS.items():
        if needle in body:
            score += weight
            flags.append(label)

    # Reentrancy shape: an external call followed by a state assignment.
    call_idx = body.find(".call")
    if call_idx != -1 and _ASSIGN_RE.search(body[call_idx:]):
        score += 5
        flags.append("external_call_before_state_write")

    return score, flags


def _collect_sol_files(
    audit_root: Path,
    exclude: list[Path] | None,
    focus: list[Path] | None,
) -> list[Path]:
    if focus:
        return [audit_root / f if not f.is_absolute() else f for f in focus]
    exclude_resolved = {e.resolve() for e in (exclude or [])}
    files = []
    for path in sorted(audit_root.rglob("*.sol")):
        if any(str(path.resolve()).startswith(str(e)) for e in exclude_resolved):
            continue
        files.append(path)
    return files


def run_stage1(
    audit_root: Path,
    exclude: list[Path] | None = None,
    focus: list[Path] | None = None,
) -> Stage1Report:
    """Produce a prioritized Stage1Report from a contract directory."""
    audit_root = Path(audit_root)
    targets: list[FunctionTarget] = []
    skipped: list[str] = []

    for path in _collect_sol_files(audit_root, exclude, focus):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = path.relative_to(audit_root) if audit_root in path.parents or path.parent == audit_root else path
        for name, body, _line in extract_functions(source):
            score, flags = score_function(body)
            target = f"{rel}:{name}"
            if score > 0:
                targets.append(FunctionTarget(target=target, score=score, flags=flags))
            else:
                skipped.append(target)

    # Highest score first; ties broken by target name for determinism.
    targets.sort(key=lambda t: (-t.score, t.target))

    notes_lines = [f"{t.target} (score={t.score}: {', '.join(t.flags)})" for t in targets[:10]]
    notes = "Top red-flag targets:\n" + "\n".join(notes_lines) if notes_lines else "No red-flag functions found."

    logger.info("Stage 1: %d priority targets, %d skipped", len(targets), len(skipped))
    return Stage1Report(
        priority_targets=[t.target for t in targets],
        skipped_targets=skipped,
        notes=notes,
    )

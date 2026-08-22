"""Reconstruct an applyable patch from an audit report's ILLUSTRATIVE fix diff (feature 025).

Why this exists: a security-audit report's ```diff``` blocks look like patches but are not
machine-applyable. They carry correct `--- a/<path>` / `+++ b/<path>` headers, but their hunk
markers are prose context — `@@ struct TRequest {`, `@@ function cancel(...) external {` — with NO
line numbers. Both standard tools reject them verbatim:

    git apply --unsafe-paths -p1   ->  "No valid patches in input"      (exit 128)
    patch -p1 --forward            ->  "I can't seem to find a patch"   (exit 2)

This is normal report style, not a defective report — so the trust mechanism that depends on
applying the report's fix (`mutation_verify`) had run 0 times across 10 passes in two live runs.

What this does: find each hunk's anchor in the REAL source, confirm every context and removal line
matches that source VERBATIM (indentation included), and emit a genuine line-numbered patch that
`git apply` accepts.

The load-bearing property is REFUSAL, not reconstruction. A patch landed in the wrong place produces
a WRONG "verified" signal — worse than no signal, because the operator would trust it. So: exactly
one anchor match, verbatim context, or `ReconstructionRefused`. No fuzzy matching, no re-indentation,
no best-guess location, ever (FR-005/FR-007/FR-010).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

_HUNK_MARKER = re.compile(r"^@@\s?(.*?)\s*@?@?\s*$")  # `@@ <anchor>` — trailing @@ optional
_REAL_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.M)  # already-applyable diff


class ReconstructionRefused(Exception):
    """Reconstruction cannot proceed with certainty. Carries a machine-readable `reason`:
    anchor_not_found | anchor_ambiguous | context_mismatch | file_not_found | malformed."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass
class _Hunk:
    anchor: str
    body: list[tuple[str, str]]  # (kind, text) with kind in {"context","removal","addition"}


@dataclass
class _FilePatch:
    path: str
    hunks: list[_Hunk]


def parse_illustrative(block: str) -> list[_FilePatch]:
    """Split an illustrative diff into per-file groups of hunks. A block may contain more than one
    `--- a/`/`+++ b/` file section; each `@@ <anchor>` starts a hunk within the current file."""
    files: list[_FilePatch] = []
    cur: _FilePatch | None = None
    hunk: _Hunk | None = None
    for raw in block.splitlines():
        if raw.startswith("--- "):
            continue  # the +++ line carries the target path
        if raw.startswith("+++ "):
            path = _strip_ab(raw[4:].strip())
            cur = _FilePatch(path=path, hunks=[])
            files.append(cur)
            hunk = None
            continue
        m = _HUNK_MARKER.match(raw)
        if m and raw.startswith("@@"):
            if cur is None:
                raise ReconstructionRefused("malformed", "hunk before any file header")
            hunk = _Hunk(anchor=m.group(1), body=[])
            cur.hunks.append(hunk)
            continue
        if hunk is None:
            continue  # prose between the header and the first hunk marker
        if raw.startswith("+"):
            hunk.body.append(("addition", raw[1:]))
        elif raw.startswith("-"):
            hunk.body.append(("removal", raw[1:]))
        else:  # context line (leading space) or a bare empty line
            hunk.body.append(("context", raw[1:] if raw.startswith(" ") else raw))
    if not files or not any(f.hunks for f in files):
        raise ReconstructionRefused("malformed", "no file section or no hunk found")
    return files


def _strip_ab(path: str) -> str:
    """Drop a leading `a/` or `b/` from a diff header path."""
    return path[2:] if path[:2] in ("a/", "b/") else path


def locate_anchor(source_lines: list[str], anchor: str) -> int:
    """Index of the single source line matching `anchor`. The auditor may have stripped the anchor's
    own leading indentation, so match on stripped equality — but require EXACTLY ONE match, so an
    abbreviated or ambiguous anchor refuses rather than landing the hunk in the wrong place."""
    key = anchor.strip()
    hits = [i for i, ln in enumerate(source_lines) if ln.strip() == key]
    if not hits:
        raise ReconstructionRefused("anchor_not_found", anchor)
    if len(hits) > 1:
        raise ReconstructionRefused("anchor_ambiguous", f"{anchor} ({len(hits)} matches)")
    return hits[0]


_TRAILING_CONTEXT = 3  # like `diff -U3`


def _reconstruct_hunk(source_lines: list[str], hunk: _Hunk, delta: int) -> tuple[str, int]:
    """Turn one anchored hunk into a real `@@ -a,b +c,d @@` block. `delta` is the net line change
    of all prior hunks in this file (additions minus removals), so the new-side start is correct.
    Returns (hunk_text, hunk_delta)."""
    i = locate_anchor(source_lines, hunk.anchor)
    # The anchor line itself becomes the hunk's first context line, emitted VERBATIM from the real
    # source (not from the possibly-stripped anchor text).
    out = [" " + source_lines[i]]
    old_count = new_count = 1
    si = i + 1
    for kind, text in hunk.body:
        if kind == "addition":
            out.append("+" + text)
            new_count += 1
            continue
        # context or removal: must match the real source line VERBATIM, whitespace included.
        if si >= len(source_lines) or source_lines[si] != text:
            found = source_lines[si] if si < len(source_lines) else "<EOF>"
            raise ReconstructionRefused(
                "context_mismatch", f"expected {text!r} at source line {si + 1}, found {found!r}")
        out.append((" " if kind == "context" else "-") + text)
        old_count += 1
        si += 1
        if kind == "context":
            new_count += 1
    # Trailing context, pulled VERBATIM from the real source (never invented) — but ONLY when the
    # hunk ends at a change. Both `git apply` and GNU `patch` REJECT a hunk that ends at a +/- line
    # with no following context (real diffs always carry it, `diff -U3`; an illustrative block often
    # does not). When the body already ends with a context line, that line IS the trailing anchor —
    # adding more would risk overlapping the NEXT hunk (observed: it swallowed the next hunk's anchor
    # line and git rejected the overlap). We have the source and exact position, so appended lines
    # are deterministic, not fuzzy. Stop before the trailing empty sentinel from splitting a file
    # that ends in "\n" (emitting it would add a spurious blank line / "no newline at EOF" mismatch).
    if hunk.body and hunk.body[-1][0] != "context":
        limit = len(source_lines) - 1 if source_lines and source_lines[-1] == "" else len(source_lines)
        for j in range(si, min(si + _TRAILING_CONTEXT, limit)):
            out.append(" " + source_lines[j])
            old_count += 1
            new_count += 1
    old_start = i + 1              # 1-based, original source
    new_start = old_start + delta  # shifted by earlier hunks' net additions
    header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@"
    return "\n".join([header, *out]), new_count - old_count


def reconstruct(block: str, read_source: Callable[[str], str | None]) -> str:
    """Illustrative diff -> a real unified diff `git apply` accepts, or `ReconstructionRefused`.

    `read_source(path)` returns the target file's text, or None if it does not exist. ALL hunks of
    ALL files must reconstruct: if any one refuses, the whole fix refuses (FR-012) — a partially
    applied fix is a wrong signal, not a partial one."""
    # Already a genuine unified diff (real `@@ -N,M +K,L @@` hunk headers)? Pass it through
    # untouched — reconstruction only exists for ILLUSTRATIVE blocks. Some reports do carry real
    # diffs, and an operator's `fix_patch` never reaches here; either way, don't second-guess a
    # patch that standard tooling can already apply.
    if _REAL_HUNK.search(block):
        return block if block.endswith("\n") else block + "\n"
    files = parse_illustrative(block)
    parts: list[str] = []
    for fp in files:
        src = read_source(fp.path)
        if src is None:
            raise ReconstructionRefused("file_not_found", fp.path)
        source_lines = src.split("\n")
        parts.append(f"--- a/{fp.path}")
        parts.append(f"+++ b/{fp.path}")
        delta = 0
        for hunk in fp.hunks:
            text, d = _reconstruct_hunk(source_lines, hunk, delta)
            parts.append(text)
            delta += d
    return "\n".join(parts) + "\n"

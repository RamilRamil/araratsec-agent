"""Feature 033 - shared low-level Solidity helpers.

The deterministic compile-fixers (scripts/solidity_fixers.py) pull in a handful of
low-level helpers that are ALSO used by poc_queue_runner.py's grounding / symbol-index /
scaffold code. Leaving them in poc_queue_runner.py and importing them into the fixer
module would create a cycle (poc_queue_runner re-exports the fixers from that module).
This module is the cycle-breaker: BOTH poc_queue_runner.py and solidity_fixers.py import
from here, and this module imports NEITHER of them.

Pure moves - the logic is byte-identical to its previous home in poc_queue_runner.py.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

POC_SUBDIR = "audit/poc"            # PoCs live here; needs FOUNDRY_TEST override

# Directories that are never part of the contest's own tracked source (build output,
# vendored deps, our own artifacts) - excluded when resolving/globbing project .sol files.
_SKIP_DIRS = {"out", "cache_forge", "node_modules", "lib", "artifacts"}


def _tracked_sol(project: Path) -> set[Path]:
    """Git-tracked .sol files - the ORIGINAL project. Excludes anything we (or a
    prior skill run) generated but never committed, so grounding/scaffold only ever
    uses the contest's own code, never our own PoCs (honesty of the workability test)."""
    try:
        out = subprocess.run(["git", "-C", str(project), "ls-files", "*.sol"],
                             capture_output=True, text=True, timeout=15)
        return {(project / line).resolve() for line in out.stdout.splitlines() if line.strip()}
    except Exception as e:
        # E1 (feature 033 follow-up): a git failure here silently drops the tracked-source
        # PREFERENCE in _fix_import_paths (candidates fall back to ALL matches, not just the
        # original repo's). Surface it once - the degradation was invisible before. The
        # deterministic shallowest-path sort keeps the pick stable even in this degraded mode.
        logger.warning("git ls-files failed in %s - tracked-source preference disabled: %s",
                       project, e)
        return set()


def _path_for(file_map: str, name: str) -> str:
    """The real import path for a contract/interface name, from [project_files]."""
    for line in file_map.splitlines():
        if line.startswith(f"{name}: "):
            return line.split(": ", 1)[1]
    return ""


def _strip_comments(sol: str) -> str:
    sol = re.sub(r"/\*.*?\*/", "", sol, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", sol)


# ── forge-output signals (feature 036: moved here so exploit_loop.py can reuse them
# without importing the heavy poc_queue_runner module). Pure regex, no deps. Behaviour
# is byte-identical to their previous home in poc_queue_runner.py; re-exported there. ──
_RAN_TEST_RE = re.compile(r"Ran \d+ tests?")


def _compiled(stdout: str, stderr: str) -> bool:
    """Did the PoC COMPILE (path-A success bar)? A runtime revert (no mainnet fork
    offline) is NOT a compile failure - distinguish a build failure from a test that
    built but reverted.

    POSITIVE signal, not a denylist: forge prints "Ran N test(s) for ..." only after
    it successfully compiled and actually executed the suite - whether the test then
    passed, failed, or reverted. A denylist of known failure strings (the previous
    approach) is fragile: it silently misclassified `Error: Encountered invalid solc
    version ...` (a real compile failure with a different message) as "compiled",
    which produced a false "all 3 compiled" result (2026-07-05) that this fixes."""
    return bool(_RAN_TEST_RE.search(stdout + "\n" + stderr))


# Stall/progress signatures key on the error MESSAGE text, never a line number - the
# model rewrites the whole file each attempt, so an identical persisting mistake lands
# on a different line every time. `Error (NNNN): <message>` drops the code and keeps the
# message; the `[FAIL: <reason>]` form covers a compiled-but-reverted run's failure reason.
def _error_signature(blob: str) -> tuple[str, ...]:
    return tuple(sorted(re.findall(r"Error \(\d+\): ([^\n]+)", blob)))


def _fail_signature(blob: str) -> tuple[str, ...]:
    return tuple(sorted(re.findall(r"\[FAIL:?\.?\s*([^\]]*)\]", blob)))


# ── Model-reply → Solidity extraction (feature 036: moved here so exploit_loop.py and
# poc_queue_runner.py share ONE definition of "what counts as code"; re-exported there,
# byte-identical). Pure text, no deps. ──
def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


# Lines whose stripped form starts with one of these anchor the start of real Solidity.
_SOLIDITY_TOKENS = ("// SPDX", "pragma", "import", "contract", "interface",
                    "library", "abstract contract")


def _extract_solidity(text: str) -> str:
    """Extract the real Solidity source from a model reply, or "" if there is none.

    Feature 015 US1: qwen3-coder:30b wraps its code in chain-of-thought prose ("Looking at
    the compilation errors… Let me analyze…") and, in tool mode, sometimes returns no code
    at all - both of which used to be written verbatim as the PoC (a spurious `Expected ';'`
    or a vacuous empty test). Anchors on the first Solidity token, then walks brace depth so
    trailing markdown fences + prose that itself contains `{`/`}` (code examples) cannot
    extend the span past the real top-level unit(s). A trailing `/* Proof Explanation */`
    is kept. A reply with no Solidity token returns ""."""
    lines = _strip_fences(text).splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if any(ln.strip().startswith(tok) for tok in _SOLIDITY_TOKENS)), None)
    if start is None:
        return ""

    def _is_solidity_start(st: str) -> bool:
        return any(st.startswith(tok) for tok in _SOLIDITY_TOKENS)

    depth = 0
    seen_body = False
    end = start
    in_block_comment = False
    for i in range(start, len(lines)):
        raw = lines[i]
        st = raw.strip()
        if seen_body and depth == 0:
            if not st:
                continue
            if st.startswith("```"):
                break
            if st.startswith("/*") or in_block_comment:
                in_block_comment = True
                end = i
                if "*/" in raw:
                    in_block_comment = False
                continue
            if _is_solidity_start(st) or st.startswith("//"):
                pass  # another top-level unit / comment - fall through
            else:
                break
        depth += raw.count("{") - raw.count("}")
        if "{" in raw:
            seen_body = True
        if depth < 0:
            depth = 0
        end = i

    if not seen_body:
        # pragma/import-only replies: stop before fences or prose
        end = start
        for i in range(start, len(lines)):
            st = lines[i].strip()
            if not st:
                continue
            if st.startswith("```"):
                break
            if _is_solidity_start(st) or st.startswith("//") or st.endswith(";"):
                end = i
                continue
            break

    return "\n".join(lines[start:end + 1]).strip()


_SCAFFOLD_CONTRACT_RE = re.compile(r"\b(?:abstract\s+)?contract\s+(\w+)\s*(?:is\b|\{)")
_SCAFFOLD_IS_RE = re.compile(r"\bcontract\s+\w+\s+is\s+([^{]+?)\s*\{")


def _scaffold_base_name(text: str) -> str | None:
    """The concrete LEAF contract to inherit from a test_scaffold file - the contract
    DECLARED in it that is not itself a base of another in-file contract (e.g. `DemoTest`,
    NOT the imported `DemoDeploy` it extends). Live H-01 run (2026-07-14): given the raw
    scaffold file, the model inherited the grandparent base and lost setUp + all the deployed
    state (`cooldownVault`, the exit constants) → a cascade of `Undeclared identifier`. The
    leaf is what actually has setUp + the state; Solidity convention puts bases first, leaf last."""
    text = _strip_comments(text or "")
    decls = _SCAFFOLD_CONTRACT_RE.findall(text)
    if not decls:
        return None
    used_as_base: set[str] = set()
    for bases in _SCAFFOLD_IS_RE.findall(text):
        used_as_base.update(b.strip() for b in bases.split(","))
    leaves = [n for n in decls if n not in used_as_base]
    return leaves[-1] if leaves else decls[-1]

#!/usr/bin/env bash
# Feature 048 / T021 — dry-run kernel carve (quickstart §1a, Phase B gate / SC-001).
#
# Proves the kernel stands alone on an ISOLATED copy, before any irreversible push:
# clone → git filter-repo (kernel path-set, promote packaging/kernel manifest to root)
# → fresh venv → pip install -e ".[dev]" → assert collected count == K → full kernel suite.
#
# In-tree green does NOT prove standalone: audit code is still physically present in the
# monorepo and can mask a kernel→audit path. This carves it away and runs with nothing but
# the kernel present. The path-set here is IDENTICAL to the real carve (T023) — only the
# destination (a scratch dir) and the absence of a push differ.
#
# Usage:  scripts/kernel_dryrun_carve.sh [dest-dir]
#   dest-dir defaults to a fresh mktemp dir. It MUST NOT exist (git clone requires it empty).
#
# Requires git-filter-repo (T001: .venv/bin/git-filter-repo). The script finds it on PATH or
# in the source repo's .venv/bin.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$(mktemp -d -t kernel-dryrun.XXXXXX)}"
K_FILE="$SRC/specs/048-repo-split/kernel-test-count.txt"
K="$(head -1 "$K_FILE" | tr -d '[:space:]')"

log() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── locate git-filter-repo (needed by `git filter-repo` on the clone) ───────────
if git filter-repo --version >/dev/null 2>&1; then
  :
elif [ -x "$SRC/.venv/bin/git-filter-repo" ]; then
  export PATH="$SRC/.venv/bin:$PATH"
  git filter-repo --version >/dev/null 2>&1 || die "git-filter-repo found but not runnable"
else
  die "git-filter-repo not on PATH nor in $SRC/.venv/bin (T001)"
fi

[ -n "$K" ] || die "could not read K from $K_FILE"
[ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ] && die "dest '$DEST' is not empty"
log "source=$SRC  dest=$DEST  expected kernel-test count K=$K"

# ── 1. clone the monorepo to the scratch dir ────────────────────────────────────
log "clone → $DEST"
rm -rf "$DEST"
git clone --quiet "$SRC" "$DEST"
cd "$DEST"

# ── 2. carve: keep ONLY the kernel path-set; promote the kernel manifest to root ─
# IDENTICAL path-set to the real carve (T023). packaging/kernel/{pyproject,README}
# are renamed to root so `pip install -e .` works while the monorepo root stays
# audit-flavored and green (FR-011).
log "git filter-repo — kernel path-set"
git filter-repo --force \
  --path sr_agent/guardrails --path sr_agent/io --path sr_agent/llm_core \
  --path sr_agent/memory --path sr_agent/models --path sr_agent/orchestrator \
  --path sr_agent/tools --path sr_agent/eval --path sr_agent/config.py \
  --path sr_agent/__init__.py --path tests/__init__.py --path tests/unit --path tests/security \
  --path tests/architecture --path tests/fixtures/__init__.py --path tests/fixtures/pack \
  --path docs/kernel.md --path LICENSE --path .gitignore \
  --path packaging/kernel/pyproject.toml --path packaging/kernel/README.md \
  --path-rename packaging/kernel/pyproject.toml:pyproject.toml \
  --path-rename packaging/kernel/README.md:README.md

# ── 2a. carve sanity: no audit code physically present (SC-002) ─────────────────
log "carve sanity — no audit code present"
[ -e sr_agent/packs ] && die "sr_agent/packs survived the carve — audit code present"
[ -e scripts ] && die "scripts/ survived the carve — audit tooling present"
[ -e frontend ] && die "frontend/ survived the carve"
[ -e pyproject.toml ] || die "root pyproject.toml missing — manifest promotion failed"
grep -q "secure-agent-kernel" pyproject.toml || die "root pyproject is not the kernel manifest"

# ── 3. fresh venv + install (no web3/docker pulled) ─────────────────────────────
log "fresh venv + pip install -e '.[dev]'"
python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"
export SR_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"

# ── 4. N+1 catch: collected count must equal K from Phase A ──────────────────────
log "collect-only — expect exactly K=$K tests"
COLLECTED="$(pytest --collect-only -q 2>/dev/null | grep -c '::' || true)"
log "collected=$COLLECTED  expected K=$K"
[ "$COLLECTED" = "$K" ] || die "collected count $COLLECTED != K ($K) — a kernel test was dropped or an audit test leaked in"

# ── 5. full kernel suite green with NO audit code present → SC-001 real ──────────
log "full kernel suite"
pytest -q

log "DRY-RUN CARVE GREEN — SC-001 proven on isolated copy at $DEST (count==K==$K). Phase B gate met."

"""Audit-pack configuration (feature 048).

Composes the task-agnostic `KernelConfig` and adds the 5 audit-owned settings
(chain keys, cloned-target workspaces, the SmartGraphical engine root) plus the
model-routing map. The seam is one-way: audit imports the kernel, never the
reverse. Attribute access delegates any kernel field (`memory_root`,
`secret_key`, …) to the composed `KernelConfig`, so composition-root code that
reads both kernel and audit settings keeps using a single `config` object.

The audit stage2 fine-tune default (`sr-stage2`) lives HERE, not in the kernel —
the kernel router resolves whatever `Mapping[str, str]` it is handed and owns no
role vocabulary. Path becomes `audit_agent/config.py` in Phase D.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sr_agent.config import KernelConfig
from sr_agent.config import config as _kernel_config


def _default_model_roles() -> dict[str, str]:
    """The audit pipeline's role→model-id map (audit owns the role vocabulary)."""
    return {
        "stage1": os.environ.get("SR_STAGE1_MODEL", "claude-opus-4-8"),
        "stage2": os.environ.get("SR_STAGE2_MODEL", "sr-stage2"),
        "stage3": os.environ.get("SR_STAGE3_MODEL", "claude-opus-4-8"),
        "poc": os.environ.get("SR_POC_MODEL", "qwen3-coder"),
    }


@dataclass(frozen=True)
class AuditConfig:
    # The composed kernel config (its 13 fields reached via attribute delegation).
    kernel: KernelConfig

    # Audit-owned settings (ownership table rows 18–22).
    alchemy_api_key: str
    tenderly_api_key: str
    # Cloned audit targets (feature 021) — a git-URL target is fetched here. MUST be
    # EXTERNAL to the agent repo (the session guard rejects paths under it), so the
    # default is the system temp dir. Gitignored; target code never enters the repo.
    workspaces_root: Path
    # Optional git token (feature 021) for cloning PRIVATE target repos. Write-only:
    # never returned/persisted/logged/argv. Empty by default (public repos need none).
    git_token: str
    # SmartGraphical engine (feature 002) — external structural+logic analyzer.
    # Empty string disables the engine; pipeline auto-skips if unset/unavailable.
    smartgraphical_root: str

    # Model routing: role → model id. Audit owns the role names and the ids; the
    # kernel router consumes this as an opaque Mapping[str, str] (feature 048).
    model_roles: Mapping[str, str]

    def __getattr__(self, name: str) -> Any:
        # Only names that are NOT real AuditConfig fields reach here; forward them
        # to the composed kernel config (its 13 fields). object.__getattribute__
        # avoids recursion if `kernel` itself is somehow absent.
        return getattr(object.__getattribute__(self, "kernel"), name)


def load_audit_config(kernel: KernelConfig | None = None) -> AuditConfig:
    return AuditConfig(
        kernel=kernel if kernel is not None else _kernel_config,
        alchemy_api_key=os.environ.get("ALCHEMY_API_KEY", ""),
        tenderly_api_key=os.environ.get("TENDERLY_API_KEY", ""),
        workspaces_root=Path(os.environ.get(
            "SR_WORKSPACES_ROOT", str(Path(tempfile.gettempdir()) / "sr-agent-workspaces"))),
        git_token=os.environ.get("GITHUB_TOKEN", ""),
        smartgraphical_root=os.environ.get("SR_SMARTGRAPHICAL_ROOT", ""),
        model_roles=_default_model_roles(),
    )


# Module-level singleton — the audit pack's config, composing the kernel singleton.
config: AuditConfig = load_audit_config()

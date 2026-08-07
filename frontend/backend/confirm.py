"""The deliberate two-step OOB approval (feature 005, US2/FR-009 — the security heart).

The UI may HOST approval, but it must never become a reflexive click. The rule:
approving a pending action requires a `confirm_token` that is issued only when
the operator fetches that action's ConsequentialActionNotice. A bare or replayed
POST never approves. Approval itself goes through the SAME kernel primitive the
CLI uses (`resolve_confirmation`), so the UI is a viewer + a deliberate trigger,
not a new authority. See specs/005-operator-frontend/contracts/approval-gate.md.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from sr_agent.orchestrator.confirmation import (
    ConfirmationStatus, load_request, resolve_confirmation,
)

# confirmation_id → the token issued when its notice was fetched. In-memory,
# single-operator. Absence of a matching token means "notice not reviewed".
_TOKENS: dict[str, str] = {}


class ApprovalError(Exception):
    pass


def issue_token(confirmation_id: str) -> str:
    """Issued ONLY when the item's notice is fetched — the deliberate-act prerequisite."""
    token = secrets.token_urlsafe(16)
    _TOKENS[confirmation_id] = token
    return token


def _valid(confirmation_id: str, token: str | None) -> bool:
    expected = _TOKENS.get(confirmation_id)
    return bool(expected) and bool(token) and secrets.compare_digest(expected, token)


def decide(
    confirmation_id: str,
    confirm_token: str | None,
    decision: str,
    confirmations_dir: Path,
) -> ConfirmationStatus:
    """Approve/reject a pending action. NEVER approves without a valid token
    (issued on notice fetch). Writes the same record as `sr-agent confirm`.

    Raises ApprovalError on a missing/invalid token or unknown decision — the
    action stays pending (fail-safe). Returns the resolved status on success.
    """
    if decision not in ("approve", "reject"):
        raise ApprovalError("decision must be 'approve' or 'reject'")

    # The gate: approving without having reviewed the notice is refused. This is
    # the FR-009 "no reflexive click / no auto-approve" property.
    if decision == "approve" and not _valid(confirmation_id, confirm_token):
        raise ApprovalError(
            "approval requires a confirm_token issued by fetching this action's "
            "notice first — a bare click cannot approve (FR-009)"
        )

    status = resolve_confirmation(
        confirmation_id, confirmations_dir, approve=(decision == "approve"),
    )
    _TOKENS.pop(confirmation_id, None)  # one-shot
    return status


def list_pending(confirmations_dir: Path) -> list[dict]:
    """The confirmation queue — pending items only (browsing, no token issued).
    Single-operator: scans the confirmations dir. Approving still requires
    fetching an item's notice first (`load_notice` → token)."""
    if not confirmations_dir.is_dir():
        return []
    import json

    out: list[dict] = []
    for path in sorted(confirmations_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("status") != "pending":
            continue
        out.append({
            "id": data.get("confirmation_id", path.stem),
            "action_type": data.get("action_type"),
            "params": data.get("params", {}),
            "created_at": data.get("created_at"),
            "state": "pending",
        })
    return out


def load_notice(confirmation_id: str, confirmations_dir: Path) -> dict:
    """Return the ConsequentialActionNotice AND issue the confirm_token (the
    deliberate-act prerequisite for `decide`)."""
    payload = load_request(confirmation_id, confirmations_dir)
    token = issue_token(confirmation_id)
    return {
        "id": confirmation_id,
        "action_type": payload.get("action_type"),
        "params": payload.get("params", {}),
        "state": payload.get("status", "pending"),
        "confirm_token": token,
    }

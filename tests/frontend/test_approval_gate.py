"""FR-009 approval gate — the frontend's security heart (feature 005, US2).

The UI may HOST approval but must never become a reflexive one-click. The property:
approving a pending write_execute requires a `confirm_token` that is issued ONLY
when the operator first fetches that action's ConsequentialActionNotice, and the
token is one-shot. Approval itself goes through the SAME kernel primitive the CLI
uses (`resolve_confirmation`) — the UI is a deliberate trigger, not a new authority.

See specs/005-operator-frontend/contracts/approval-gate.md (gates G1-G4).
"""
from __future__ import annotations

import os

os.environ.setdefault("SR_SECRET_KEY", "00" * 32)

import pytest

from sr_agent.models.action import Action, ActionType
from sr_agent.orchestrator.confirmation import (
    ConfirmationStatus, load_request, request_confirmation,
)

from frontend.backend import confirm


def _pending(tmp_path):
    """Create a real pending write_execute confirmation via the kernel primitive."""
    action = Action(action_type=ActionType.write_poc, params={"finding_id": "F1"})
    req = request_confirmation(action, tmp_path)
    return req.confirmation_id


# ── G2: a bare POST cannot approve (no reflexive click / no auto-approve) ──────

def test_G2_approve_without_token_is_refused(tmp_path):
    cid = _pending(tmp_path)
    with pytest.raises(confirm.ApprovalError):
        confirm.decide(cid, None, "approve", tmp_path)
    # Fail-safe: the action is untouched — still pending.
    assert load_request(cid, tmp_path)["status"] == ConfirmationStatus.pending.value


def test_G4_wrong_token_is_refused(tmp_path):
    cid = _pending(tmp_path)
    confirm.load_notice(cid, tmp_path)  # issues the real token, which we ignore
    with pytest.raises(confirm.ApprovalError):
        confirm.decide(cid, "not-the-real-token", "approve", tmp_path)
    assert load_request(cid, tmp_path)["status"] == ConfirmationStatus.pending.value


# ── G3: fetch-notice-then-approve works, and writes the SAME OOB record ────────

def test_G3_notice_then_approve_resolves(tmp_path):
    cid = _pending(tmp_path)
    notice = confirm.load_notice(cid, tmp_path)
    assert notice["action_type"] == "write_poc"
    token = notice["confirm_token"]

    status = confirm.decide(cid, token, "approve", tmp_path)
    assert status is ConfirmationStatus.approved
    # Same record the CLI `sr-agent confirm` would write — resolved on disk.
    assert load_request(cid, tmp_path)["status"] == ConfirmationStatus.approved.value


def test_token_is_one_shot_no_replay(tmp_path):
    cid = _pending(tmp_path)
    token = confirm.load_notice(cid, tmp_path)["confirm_token"]
    confirm.decide(cid, token, "approve", tmp_path)
    # Replaying the same token cannot approve again (one-shot).
    with pytest.raises(confirm.ApprovalError):
        confirm.decide(cid, token, "approve", tmp_path)


# ── G1: rejection is always allowed (fail-safe), no token needed ──────────────

def test_G1_reject_needs_no_token(tmp_path):
    cid = _pending(tmp_path)
    status = confirm.decide(cid, None, "reject", tmp_path)
    assert status is ConfirmationStatus.rejected
    assert load_request(cid, tmp_path)["status"] == ConfirmationStatus.rejected.value


def test_unknown_decision_refused(tmp_path):
    cid = _pending(tmp_path)
    with pytest.raises(confirm.ApprovalError):
        confirm.decide(cid, None, "maybe", tmp_path)
    assert load_request(cid, tmp_path)["status"] == ConfirmationStatus.pending.value

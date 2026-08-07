"""Out-of-band confirmation tests (US4, SC-003).

Verifies that irreversible actions cannot proceed without an explicit
out-of-band approval, and that the channel fails safe (timeout => rejected).
No LLM and no Docker required — this is the deterministic security boundary.
"""
import json
import pytest
from pathlib import Path

from sr_agent.models.action import Action, ActionType
from sr_agent.orchestrator.confirmation import (
    ConfirmationStatus,
    check_confirmation,
    load_request,
    request_confirmation,
    resolve_confirmation,
)


@pytest.fixture
def confirmations_dir(tmp_path: Path) -> Path:
    return tmp_path / "confirmations"


def _write_poc_action() -> Action:
    return Action(action_type=ActionType.write_poc, params={"finding_id": "HIGH-001"})


def test_irreversible_pauses(confirmations_dir):
    """Requesting confirmation creates a pending request on disk."""
    req = request_confirmation(_write_poc_action(), confirmations_dir)
    assert req.path.exists()
    data = json.loads(req.path.read_text())
    assert data["status"] == "pending"
    assert data["action_type"] == "write_poc"
    assert data["params"]["finding_id"] == "HIGH-001"


def test_approve_proceeds(confirmations_dir):
    """An out-of-band approval lets the action proceed."""
    req = request_confirmation(_write_poc_action(), confirmations_dir)
    resolve_confirmation(req.confirmation_id, confirmations_dir, approve=True)
    status = check_confirmation(req.confirmation_id, confirmations_dir, timeout_s=0)
    assert status is ConfirmationStatus.approved


def test_reject_cancels_action(confirmations_dir):
    """An out-of-band rejection cancels the action and records the reason."""
    req = request_confirmation(_write_poc_action(), confirmations_dir)
    resolve_confirmation(
        req.confirmation_id, confirmations_dir, approve=False, reason="looks malicious"
    )
    status = check_confirmation(req.confirmation_id, confirmations_dir, timeout_s=0)
    assert status is ConfirmationStatus.rejected
    data = json.loads(req.path.read_text())
    assert data["decided_reason"] == "looks malicious"


def test_timeout_rejects(confirmations_dir):
    """No decision before the deadline => fail-safe reject, recorded as timeout."""
    req = request_confirmation(_write_poc_action(), confirmations_dir)
    status = check_confirmation(req.confirmation_id, confirmations_dir, timeout_s=0)
    assert status is ConfirmationStatus.rejected
    data = json.loads(req.path.read_text())
    assert data["decided_reason"] == "timeout"


def test_pending_is_not_approved(confirmations_dir):
    """A pending request must never be treated as approved-by-default."""
    req = request_confirmation(_write_poc_action(), confirmations_dir)
    status = check_confirmation(req.confirmation_id, confirmations_dir, timeout_s=0)
    assert status is ConfirmationStatus.rejected


def test_resolve_unknown_id_raises(confirmations_dir):
    """Deciding on a non-existent confirmation is an error, not a silent approve."""
    with pytest.raises(FileNotFoundError):
        resolve_confirmation("nonexistent", confirmations_dir, approve=True)


def test_load_request_shows_details(confirmations_dir):
    req = request_confirmation(_write_poc_action(), confirmations_dir)
    data = load_request(req.confirmation_id, confirmations_dir)
    assert data["action_type"] == "write_poc"
    assert data["status"] == "pending"

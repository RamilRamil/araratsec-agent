"""Characterization / parity guard for the action-taxonomy relocation (feature 002, FR-009).

Captured on `main` BEFORE any relocation lands (guard independence): if this
fixture were created by the same commit that moves the metadata into the pack, it
could not witness a regression that move introduces. It pins the three BATCH-side
observable surfaces the relocation must preserve byte-for-byte (SC-004 "empty
diff"):

  1. the gated-action set — which action ids the kernel confirms out-of-band
     (⟺ `action_class == write_execute`);
  2. the statuses that require human confirmation (the pack's privileged set);
  3. PoC output for a fixed synthetic finding id.

It is written kernel-version-agnostically ON PURPOSE: it reads `action_class`
straight off the pack's `ActionSpec`s and calls `write_poc` as the pure audit
function it is — so the SAME test runs identically against the pre-migration
kernel (domain ids in `sr_agent`) and the post-migration feature-001 kernel
(domain ids in `audit_agent`). What changes across the move — e.g. that
`AUDIT_PACK.actions` becomes domain-only — is deliberately NOT snapshotted here;
only the invariant behavior is. Chat-path parity is covered separately (T016);
this guard is batch-surface only.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from audit_agent.pack import AUDIT_PACK
from audit_agent.tools.write_execute import write_poc

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "taxonomy_characterization"


def _gated_action_ids() -> list[str]:
    """Ids the kernel gates for OOB confirmation ⟺ action_class == write_execute.

    Computed from the pack's declared ActionSpecs — invariant across the move of
    those specs from kernel to pack.
    """
    return sorted(
        action_id
        for action_id, spec in AUDIT_PACK.actions.items()
        if spec.action_class.value == "write_execute"
    )


def test_gated_action_set_is_unchanged():
    golden = json.loads((_FIXTURES / "gated_actions.json").read_text())
    assert _gated_action_ids() == golden


def test_confirming_status_set_is_unchanged():
    golden = json.loads((_FIXTURES / "confirming_statuses.json").read_text())
    assert sorted(AUDIT_PACK.privileged_statuses) == golden


def test_poc_output_is_byte_identical():
    golden = (_FIXTURES / "poc_HIGH-001.t.sol").read_text()
    with tempfile.TemporaryDirectory() as d:
        result = write_poc("HIGH-001", Path(d) / "poc", generator=None)
        produced = result.path.read_text()
    assert result.path.name == "HIGH_001.t.sol"
    assert produced == golden

"""Executable-surface contract: classification, vocabulary, and dispatch identity."""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from sr_agent.models.action import Action, ActionClass, ValidationStatus
from sr_agent.orchestrator.action import validate_action
from sr_agent.orchestrator.context import wrap_data
from sr_agent.orchestrator.pack import PackContext
from sr_agent.tools.sandbox import SandboxResult

from audit_agent.actions import ACTION_CLASS_MAP, AuditActionType
from audit_agent.agent_tool_surface import AGENT_TOOL_SURFACE, SurfaceEntry
from audit_agent.pack import AUDIT_PACK
from audit_agent.reasoning import AUDIT_CHAT_SYSTEM

_KERNEL_READS = ("read_file", "search_code")
_FILEPATH_PARAMS = frozenset({"path", "target"})


def test_every_declared_id_has_one_surface_entry():
    declared = {t.value for t in AuditActionType} | set(_KERNEL_READS)
    assert set(AGENT_TOOL_SURFACE) == declared
    for entry in AGENT_TOOL_SURFACE.values():
        assert not (entry.offered and not entry.available)


def test_write_execute_ids_are_not_offered():
    for t, cls in ACTION_CLASS_MAP.items():
        if cls is ActionClass.write_execute:
            assert AGENT_TOOL_SURFACE[t.value].offered is False


def test_missing_target_rejected_for_analyzers(tmp_path):
    for aid in (AuditActionType.run_slither.value, AuditActionType.run_mythril.value):
        result = validate_action(Action(action_type=aid, params={}), tmp_path, AUDIT_PACK)
        assert result.status is ValidationStatus.rejected
        assert result.rejection_reason


def _bind_valid(params: dict, tmp_path: Path) -> dict:
    out = dict(params)
    for key in _FILEPATH_PARAMS:
        if key in out:
            dest = tmp_path / str(out[key])
            if not dest.exists():
                dest.write_text("contract Vault {}\n")
            out[key] = str(dest)
    return out


def test_prompt_lists_every_offered_id_with_params():
    for tool_id, entry in AGENT_TOOL_SURFACE.items():
        if not entry.offered:
            continue
        assert f'"{tool_id}"' in AUDIT_CHAT_SYSTEM
        for name in entry.required_params:
            assert f'"{name}"' in AUDIT_CHAT_SYSTEM
    assert '"complete"' in AUDIT_CHAT_SYSTEM
    for t, cls in ACTION_CLASS_MAP.items():
        if cls is ActionClass.write_execute:
            assert t.value not in AUDIT_CHAT_SYSTEM


def test_required_param_deletion_is_rejected(tmp_path):
    for tool_id, entry in AGENT_TOOL_SURFACE.items():
        if not entry.offered:
            continue
        valid = _bind_valid(entry.valid_params, tmp_path)
        accepted = validate_action(
            Action(action_type=tool_id, params=valid), tmp_path, AUDIT_PACK,
        )
        assert accepted.status is ValidationStatus.approved, (
            f"{tool_id} valid example rejected: {accepted.rejection_reason}"
        )
        for name in entry.required_params:
            # Kernel _validate_read_file uses _check_filepath(..., require_str=False)
            # (FR-013: no kernel edit). Missing path is a kernel gap, not a pack one.
            if tool_id == "read_file" and name == "path":
                continue
            bad = dict(valid)
            bad.pop(name, None)
            result = validate_action(
                Action(action_type=tool_id, params=bad), tmp_path, AUDIT_PACK,
            )
            assert result.status is ValidationStatus.rejected, (
                f"{tool_id} missing {name!r} was accepted"
            )


def test_filepath_escape_rejected(tmp_path):
    outside = str(tmp_path.parent / "escape.sol")
    for tool_id, entry in AGENT_TOOL_SURFACE.items():
        if not entry.offered:
            continue
        fp_names = [n for n in entry.required_params if n in _FILEPATH_PARAMS]
        if not fp_names:
            continue
        valid = _bind_valid(entry.valid_params, tmp_path)
        for name in fp_names:
            bad = dict(valid)
            bad[name] = outside
            result = validate_action(
                Action(action_type=tool_id, params=bad), tmp_path, AUDIT_PACK,
            )
            assert result.status is ValidationStatus.rejected, (
                f"{tool_id} escaped {name!r} was accepted"
            )


def test_dispatch_invokes_entry_executor(tmp_path, monkeypatch):
    called: list[str] = []

    def sentinel(action, ctx):
        called.append(action.action_type)
        return ctx.wrap_data("SENTINEL", tool=action.action_type, path="")

    ctx = PackContext(
        scope_root=tmp_path,
        sandbox=_NullSandbox(),
        wrap_data=wrap_data,
    )
    for tool_id, entry in list(AGENT_TOOL_SURFACE.items()):
        if not entry.offered:
            continue
        spy: SurfaceEntry = replace(entry, executor=sentinel)
        monkeypatch.setitem(AGENT_TOOL_SURFACE, tool_id, spy)
        called.clear()
        out = AUDIT_PACK.dispatch(Action(action_type=tool_id, params={}), ctx)
        assert called == [tool_id], f"{tool_id} did not invoke its contract executor"
        assert "SENTINEL" in out
        assert "[STUB]" not in out


def test_prompt_next_action_list_equals_offered_plus_complete():
    ids = re.findall(r'^- "([a-z_]+)"', AUDIT_CHAT_SYSTEM, flags=re.M)
    expected = [k for k, e in AGENT_TOOL_SURFACE.items() if e.offered] + ["complete"]
    assert ids == expected


class _NullSandbox:
    def run(self, *a, **k):
        return SandboxResult(exit_code=0, stdout="", stderr="")

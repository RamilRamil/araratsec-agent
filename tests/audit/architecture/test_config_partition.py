"""US4 / FR-001 (audit side) — the 22 fields partition exactly across the seam.

Audit-side because it imports BOTH `KernelConfig` (from the kernel) and
`AuditConfig` (audit) — only the audit repo, which composes the kernel, can see
both. Lives under tests/audit/** so it stays in Repo B (Phase D) and out of the
kernel carve path-set. Written test-first: RED until T009/T010 land.

Asserts KernelConfig(13) ∪ AuditConfig.audit(5) ∪ model_roles(4) == the original
22, pairwise-disjoint — no field orphaned, none duplicated across the seam.

See specs/048-repo-split/spec.md (Configuration ownership) and data-model.md.
"""
from __future__ import annotations

import dataclasses

ORIGINAL_22 = {
    "anthropic_api_key", "gemini_api_key", "openrouter_api_key", "secret_key",
    "memory_root", "knowledge_root", "confirmations_root", "relay_root", "lessons_root",
    "langfuse_secret_key", "langfuse_public_key", "langfuse_host", "langfuse_enabled",
    "alchemy_api_key", "tenderly_api_key", "workspaces_root", "git_token",
    "smartgraphical_root",
    "stage1_model", "stage2_model", "stage3_model", "poc_model",
}
KERNEL_13 = {
    "anthropic_api_key", "gemini_api_key", "openrouter_api_key", "secret_key",
    "memory_root", "knowledge_root", "confirmations_root", "relay_root", "lessons_root",
    "langfuse_secret_key", "langfuse_public_key", "langfuse_host", "langfuse_enabled",
}
AUDIT_5 = {
    "alchemy_api_key", "tenderly_api_key", "workspaces_root", "git_token",
    "smartgraphical_root",
}


def _field_names(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def test_audit_config_composes_kernel_and_owns_the_5_audit_fields() -> None:
    from sr_agent.config import KernelConfig
    from audit_agent.config import AuditConfig

    fields = _field_names(AuditConfig)
    assert AUDIT_5 <= fields, f"AuditConfig missing audit fields: {sorted(AUDIT_5 - fields)}"
    assert "model_roles" in fields, "AuditConfig must expose model_roles (role→model_id)"
    # Kernel is composed, not re-declared flat: no kernel field name appears as an
    # AuditConfig field other than via the composed KernelConfig handle.
    kernel_fields = _field_names(KernelConfig)
    assert kernel_fields.isdisjoint(fields - {"model_roles"}), (
        "AuditConfig must compose KernelConfig, not duplicate its fields"
    )


def test_model_roles_maps_the_four_routing_roles_with_audit_default() -> None:
    from audit_agent.config import load_audit_config

    roles = dict(load_audit_config().model_roles)
    assert set(roles) == {"stage1", "stage2", "stage3", "poc"}, (
        f"model_roles must map the four audit routing roles, got {sorted(roles)}"
    )
    # The audit stage2 fine-tune default lives on the audit side, not in the kernel.
    assert roles["stage2"] == "sr-stage2"


def test_the_22_fields_partition_with_no_orphan_or_duplicate() -> None:
    from sr_agent.config import KernelConfig
    from audit_agent.config import AuditConfig, load_audit_config

    kernel = _field_names(KernelConfig)
    audit_direct = _field_names(AuditConfig) & AUDIT_5
    roles = set(load_audit_config().model_roles)
    roles_as_fields = {f"{r}_model" for r in roles}

    covered = kernel | audit_direct | roles_as_fields
    assert covered == ORIGINAL_22, (
        f"the 22 fields must partition with no orphan/duplicate.\n"
        f"  uncovered: {sorted(ORIGINAL_22 - covered)}\n"
        f"  extra: {sorted(covered - ORIGINAL_22)}"
    )
    assert kernel.isdisjoint(audit_direct)
    assert kernel.isdisjoint(roles_as_fields)
    assert audit_direct.isdisjoint(roles_as_fields)

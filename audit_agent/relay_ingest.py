"""Relay finding-adaptation — audit pack (feature 004).

The kernel `relay.py` keeps the transport (request packets, response files,
generic `extract_findings` → list[dict]). Turning those dicts into validated
domain `Finding`s is audit knowledge and lives here. Shared by the manual relay
and the local-model analyze path so both parse identically: tolerant fenced-JSON
extraction, strict Finding validation, sanitized notes, and the structural drop
of any status_change (relay/automation != authoring).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sr_agent.guardrails.sanitize import sanitize
from sr_agent.orchestrator.relay import (
    RelayAdapterError, _response_path, extract_findings,
)
from audit_agent.finding import Finding

logger = logging.getLogger(__name__)


@dataclass
class RelayFinding:
    finding: Finding
    notes: str               # sanitized
    notes_flags: list[str]   # sanitize flags (homoglyph, zero_width, ...)


@dataclass
class RelayIngestResult:
    request_id: str
    findings: list[RelayFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    needs_resend: bool = False

    @property
    def ok(self) -> bool:
        return not self.needs_resend and bool(self.findings)


def adapt_findings(raw_text: str, request_id: str = "") -> RelayIngestResult:
    """Turn free-form model text into validated findings."""
    result = RelayIngestResult(request_id=request_id)

    try:
        raw_findings = extract_findings(raw_text)
    except RelayAdapterError as e:
        result.needs_resend = True
        result.errors.append(str(e))
        return result

    for idx, raw in enumerate(raw_findings):
        raw = dict(raw)  # copy; do not mutate caller data
        notes = raw.pop("notes", "") or ""
        # status_change is not a Finding field — dropped so a model response can
        # never carry a privileged status into memory.
        raw.pop("status_change", None)
        try:
            finding = Finding(**raw)
        except Exception as e:
            result.errors.append(f"finding[{idx}]: {e}")
            continue
        clean = sanitize(str(notes))
        result.findings.append(
            RelayFinding(finding=finding, notes=clean.normalized, notes_flags=clean.flags)
        )

    if not result.findings and not result.errors:
        result.errors.append("response contained zero findings")
    return result


def ingest_response(
    request_id: str,
    relay_dir: Path,
    response_text: str | None = None,
) -> RelayIngestResult:
    """Parse and validate a relayed analysis response into findings (fail-safe)."""
    if response_text is None:
        path = _response_path(relay_dir, request_id)
        if not path.exists():
            result = RelayIngestResult(request_id=request_id)
            result.needs_resend = True
            result.errors.append("no response file found")
            return result
        response_text = path.read_text(encoding="utf-8")

    result = adapt_findings(response_text, request_id=request_id)
    logger.info(
        "Relay ingest %s: %d valid, %d errors%s",
        request_id, len(result.findings), len(result.errors),
        " (needs_resend)" if result.needs_resend else "",
    )
    return result

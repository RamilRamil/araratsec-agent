"""Pack-owned payload shapes inside kernel dispatch_payload bodies."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from audit_agent.finding import Finding

TransitionType = Literal["discover", "check", "synthesize", "skip", "gap"]
StageOutcome = Literal["ran", "did_not_run", "timeout", "skipped", "empty"]
AnalyzerOutcome = Literal["ran", "did_not_run", "timeout"]
RoadmapState = Literal["pending", "analysed", "skipped", "gap"]


class StageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["stage_event"] = "stage_event"
    transition_type: TransitionType
    roadmap_revision: int = 0
    chunk_id: str | None = None
    target: str | None = None
    outcome: StageOutcome
    reason: str | None = None
    as_of_sequence: int = 0
    targets: tuple[str, ...] = ()
    skipped_targets: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _required_fields(self) -> StageEvent:
        if self.transition_type == "discover" and not self.chunk_id:
            raise ValueError("discover requires chunk_id")
        if self.transition_type in ("check", "skip", "gap") and not self.target:
            raise ValueError(f"{self.transition_type} requires target")
        if self.transition_type in ("skip", "gap") and not (self.reason or "").strip():
            raise ValueError(f"{self.transition_type} requires a non-empty reason")
        return self


class AnalyzerExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["analyzer_execution"] = "analyzer_execution"
    analyzer_id: str
    analyzer_version: str
    target: str
    target_digest: str
    analyzer_outcome: AnalyzerOutcome
    result_truncated: str = ""
    finding_ids: tuple[str, ...] = ()


class RoadmapRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    state: RoadmapState
    reason: str | None = None
    chunk_id: str | None = None


class ProjectedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    location: str
    severity: str
    tags: tuple[str, ...] = ()
    preconditions: dict[int, bool] = Field(default_factory=dict)
    notes: str = ""
    grounded: bool = False
    analyzer_id: str | None = None


class RoadmapProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of_sequence: int
    targets: tuple[RoadmapRow, ...] = ()
    findings: tuple[ProjectedFinding, ...] = ()
    empty_label: str | None = None


class CanonicalParityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_type: str | None = None
    chunk_id: str | None = None
    analyzer_id: str | None = None
    target: str | None = None
    analyzer_outcome: str | None = None
    grounded: bool = False
    location: str = ""
    severity: str = ""
    tags: tuple[str, ...] = ()
    preconditions: dict[int, bool] = Field(default_factory=dict)
    notes: str = ""


class MethodologyTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_event: StageEvent
    executions: tuple[AnalyzerExecution, ...] = ()
    findings: tuple[Finding, ...] = ()
    projection: RoadmapProjection
    pending: object | None = None

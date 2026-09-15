from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReadinessStatus(StrEnum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class ReadinessFindingImpact(StrEnum):
    BLOCKING = "blocking"
    REVIEW = "review"


class CareerProfileReadinessFinding(BaseModel):
    """A neutral, traceable condition affecting generation safety."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    impact: ReadinessFindingImpact
    message: str
    source_references: tuple[str, ...] = Field(default_factory=tuple)
    recommended_action: str | None = None


class TrustedProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trusted_contact_anchor_count: int
    experience_with_trusted_fact_count: int
    education_with_trusted_fact_count: int
    trusted_skill_count: int
    trusted_tool_count: int
    trusted_certification_count: int
    trusted_project_count: int
    trusted_publication_count: int
    unresolved_count: int


class CareerProfileReadinessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ReadinessStatus
    findings: tuple[CareerProfileReadinessFinding, ...] = Field(default_factory=tuple)
    blocking_findings: tuple[CareerProfileReadinessFinding, ...] = Field(default_factory=tuple)
    review_findings: tuple[CareerProfileReadinessFinding, ...] = Field(default_factory=tuple)
    trusted_summary: TrustedProfileSummary
    unresolved_count: int
    policy_version: str = "v1"

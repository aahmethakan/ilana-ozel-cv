from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.job import JobRequirement
from app.services.job_analysis.schemas import UnresolvedJobItem


class RequirementMatchStatus(StrEnum):
    MATCHED = "matched"
    PARTIAL = "partial"
    NOT_EVIDENCED = "not_evidenced"
    NOT_EVALUABLE = "not_evaluable"


class RequirementMatchType(StrEnum):
    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    CONTROLLED_SEMANTIC = "controlled_semantic"
    PARTIAL = "partial"
    UNMATCHED = "unmatched"


class RequirementMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement: JobRequirement
    status: RequirementMatchStatus
    matched_evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    reason_code: str
    explanation: str
    match_type: RequirementMatchType = RequirementMatchType.UNMATCHED
    confidence: str = "none"


class JobMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_results: tuple[RequirementMatchResult, ...] = Field(default_factory=tuple)
    matched_required_count: int = 0
    matched_preferred_count: int = 0
    not_evidenced_required_count: int = 0
    not_evidenced_preferred_count: int = 0
    partial_count: int = 0
    not_evaluable_count: int = 0
    unresolved_job_items: tuple[UnresolvedJobItem, ...] = Field(default_factory=tuple)

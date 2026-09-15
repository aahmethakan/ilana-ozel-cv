from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class JobMatchScoringPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "v1"
    required_weight: int = 2
    preferred_weight: int = 1
    unknown_weight: int = 1
    matched_units: int = 2
    partial_units: int = 1
    not_evidenced_units: int = 0


class JobMatchScoreFindingSeverity(StrEnum):
    INFO = "info"
    LIMITATION = "limitation"


class JobMatchScoreFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: JobMatchScoreFindingSeverity
    message: str


class JobMatchScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    matched_count: int
    partial_count: int
    not_evidenced_count: int
    not_evaluable_count: int
    required_count: int
    preferred_count: int
    unknown_importance_count: int
    unknown_importance_evaluable_count: int
    evaluated_count: int
    structured_requirement_count: int
    unresolved_job_item_count: int
    duplicate_result_count: int
    conflicting_duplicate_result_count: int
    weighted_earned_units: int
    weighted_possible_units: int


class JobMatchScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: JobMatchScoringPolicy
    match_score: int | None = None
    evaluation_coverage: int | None = None
    required_match_score: int | None = None
    required_evaluation_coverage: int | None = None
    preferred_match_score: int | None = None
    preferred_evaluation_coverage: int | None = None
    breakdown: JobMatchScoreBreakdown
    findings: tuple[JobMatchScoreFinding, ...] = Field(default_factory=tuple)

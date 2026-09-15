from pydantic import BaseModel, ConfigDict, Field

from app.domain.job import RequirementCategory, RequirementImportance
from app.services.career_gap_analysis import CoachQuestion, GapPriority
from app.services.job_match import RequirementMatchStatus


class JobCoachContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_questions: int = Field(default=5, ge=1, le=8)


class JobCoachQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: CoachQuestion
    requirement_id: str
    requirement_text: str
    requirement_category: RequirementCategory
    importance: RequirementImportance
    match_status: RequirementMatchStatus
    job_source_references: tuple[str, ...]


class JobCoachSkippedRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    requirement_text: str
    category: RequirementCategory
    importance: RequirementImportance
    match_status: RequirementMatchStatus | None = None
    reason_code: str
    job_source_references: tuple[str, ...]


class JobCoachResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    questions: tuple[JobCoachQuestion, ...] = Field(default_factory=tuple)
    skipped_requirements: tuple[JobCoachSkippedRequirement, ...] = Field(default_factory=tuple)
    eligible_count: int = 0
    generated_count: int = 0
    truncated_count: int = 0

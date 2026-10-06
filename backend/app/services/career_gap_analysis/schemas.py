from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GapCategory(StrEnum):
    CERTIFICATION = "certification"
    LANGUAGE = "language"
    SKILL = "skill"
    METRIC = "metric"
    TOOL = "tool"
    LEADERSHIP = "leadership"
    PROJECT_MANAGEMENT = "project_management"


class GapPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AnswerType(StrEnum):
    YES_NO_DETAILS = "yes_no_details"
    FREE_TEXT = "free_text"


class GapAnalysisContext(BaseModel):
    """Optional, caller-supplied context; it does not create evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_role: str | None = None
    target_job_keywords: tuple[str, ...] = Field(default_factory=tuple)
    career_direction: str | None = None
    locale: str | None = None
    cv_language: str | None = None
    max_questions: int = Field(default=6, ge=1, le=8)


class CoachQuestion(BaseModel):
    """A user question about absent evidence, never a claim about the user."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str
    category: GapCategory
    question_text: str
    reason: str
    target_section: str
    priority: GapPriority
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    missing_signal: str
    answer_type: AnswerType
    related_role: str | None = None
    question_type: str | None = None
    related_requirement_id: str | None = None
    expected_information: str | None = None
    potential_impact: str | None = None
    status: str = "open"


class SkippedOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: GapCategory
    reason_code: str


class GapAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    questions: tuple[CoachQuestion, ...] = Field(default_factory=tuple)
    skipped_opportunities: tuple[SkippedOpportunity, ...] = Field(default_factory=tuple)
    total_recommendations: int = Field(default=0, ge=0)
    more_recommendations_available: bool = False

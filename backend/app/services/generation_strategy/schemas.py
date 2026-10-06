from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GenerationMode(StrEnum):
    TARGETED = "targeted"
    GENERAL = "general"


class GenerationTargetSection(StrEnum):
    WORK_EXPERIENCE = "work_experience"
    SKILLS = "skills"
    OTHER = "other"


class GenerationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    requirement_id: str | None = None
    atomic_evidence_id: str
    target_section: GenerationTargetSection
    selection_reason: str
    association_evidence_id: str | None = None
    work_record_id: str | None = None
    work_candidate_id: str | None = None


class GenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: GenerationMode
    selections: tuple[GenerationSelection, ...] = Field(default_factory=tuple)

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Annotated

from app.domain.document import SectionType

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CandidateType(StrEnum):
    WORK_EXPERIENCE = "work_experience"
    EDUCATION = "education"
    SKILL = "skill"
    LANGUAGE = "language"
    CERTIFICATION = "certification"
    PROJECT = "project"
    PUBLICATION = "publication"
    CONTACT = "contact"


class AIConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceContext(BaseModel):
    """Only source evidence intentionally supplied for one AI interpretation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: NonEmptyText
    original_text: NonEmptyText
    section_type: SectionType | None = None


class AIInterpretationRequest(BaseModel):
    """A bounded, structured request without unrelated CV context or hidden reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: tuple[EvidenceContext, ...] = Field(min_length=1)
    target_category: CandidateType | None = None


class CandidateField(BaseModel):
    """A proposed structured value, for example title or company."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyText
    value: NonEmptyText


class AIProposedCandidate(BaseModel):
    """Structured, user-safe AI proposal; it is never a trusted career fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_type: CandidateType
    proposed_statement: NonEmptyText
    evidence_references: tuple[NonEmptyText, ...] = Field(min_length=1)
    confidence: AIConfidence
    rationale: NonEmptyText | None = None
    requires_user_confirmation: bool = True
    proposed_fields: tuple[CandidateField, ...] = Field(default_factory=tuple)


class AIInterpretationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[AIProposedCandidate, ...] = Field(default_factory=tuple)

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.confirmation.structured.schemas import StructuredRecordType
from app.extraction.career import UnresolvedEvidence


class WorkExperienceField(StrEnum):
    COMPANY = "company"
    TITLE = "title"
    LOCATION = "location"
    START_DATE = "start_date"
    END_DATE = "end_date"
    IS_CURRENT = "is_current"


class EducationField(StrEnum):
    INSTITUTION = "institution"
    DEGREE = "degree"
    FIELD_OF_STUDY = "field_of_study"
    START_DATE = "start_date"
    END_DATE = "end_date"


class WorkEvidenceResolutionBinding(BaseModel):
    """An explicit, field-scoped bridge from coarse unresolved evidence to one work candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_key: str
    record_type: Literal[StructuredRecordType.WORK_EXPERIENCE] = StructuredRecordType.WORK_EXPERIENCE
    record_id: str
    candidate_id: str
    field_name: WorkExperienceField


class EducationEvidenceResolutionBinding(BaseModel):
    """An explicit, field-scoped bridge from coarse unresolved evidence to one education candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_key: str
    record_type: Literal[StructuredRecordType.EDUCATION] = StructuredRecordType.EDUCATION
    record_id: str
    candidate_id: str
    field_name: EducationField


EvidenceResolutionBinding = WorkEvidenceResolutionBinding | EducationEvidenceResolutionBinding


class EvidenceConvergenceState(StrEnum):
    RESOLVED = "resolved"
    STILL_UNRESOLVED = "still_unresolved"
    REJECTED = "rejected"
    CONFLICT = "conflict"


class EvidenceConvergenceBasis(StrEnum):
    PREEXISTING_VERIFIED = "preexisting_verified"
    PREEXISTING_USER_PROVIDED = "preexisting_user_provided"
    USER_CONFIRMED = "user_confirmed"
    USER_CORRECTED = "user_corrected"
    USER_REJECTED = "user_rejected"
    UNRESOLVED = "unresolved"
    STRUCTURED_CONFLICT = "structured_conflict"


class EvidenceConvergenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_key: str
    record_type: StructuredRecordType | None = None
    record_id: str | None = None
    candidate_id: str | None = None
    field_name: WorkExperienceField | EducationField
    state: EvidenceConvergenceState
    basis: EvidenceConvergenceBasis
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)
    related_record_ids: tuple[str, ...] = Field(default_factory=tuple)
    related_candidate_ids: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_state_basis(self) -> "EvidenceConvergenceItem":
        allowed_bases = {
            EvidenceConvergenceState.RESOLVED: {
                EvidenceConvergenceBasis.PREEXISTING_VERIFIED,
                EvidenceConvergenceBasis.PREEXISTING_USER_PROVIDED,
                EvidenceConvergenceBasis.USER_CONFIRMED,
                EvidenceConvergenceBasis.USER_CORRECTED,
            },
            EvidenceConvergenceState.STILL_UNRESOLVED: {EvidenceConvergenceBasis.UNRESOLVED},
            EvidenceConvergenceState.REJECTED: {EvidenceConvergenceBasis.USER_REJECTED},
            EvidenceConvergenceState.CONFLICT: {EvidenceConvergenceBasis.STRUCTURED_CONFLICT},
        }
        if self.basis not in allowed_bases[self.state]:
            raise ValueError("Evidence convergence state and basis must be compatible.")
        return self


class EvidenceConvergenceResult(BaseModel):
    """Immutable current convergence view; extraction evidence remains unchanged historical input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[EvidenceConvergenceItem, ...] = Field(default_factory=tuple)
    unbound_unresolved_evidence: tuple[UnresolvedEvidence, ...] = Field(default_factory=tuple)

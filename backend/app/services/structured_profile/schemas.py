from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.confirmation.structured.schemas import (
    ResolvedEducation,
    ResolvedWorkExperience,
    StructuredRecordType,
    StructuredResolutionStatus,
)

_ADMISSIBLE_STATUSES = {StructuredResolutionStatus.RESOLVED, StructuredResolutionStatus.PARTIALLY_RESOLVED}


class StructuredWorkExperienceEntry(BaseModel):
    """Current provenance-aware work record state, without duplicating its resolution audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ResolvedWorkExperience
    resolution_status: StructuredResolutionStatus
    candidate_id: str

    @model_validator(mode="after")
    def validate_admissible_status(self) -> "StructuredWorkExperienceEntry":
        if self.resolution_status not in _ADMISSIBLE_STATUSES:
            raise ValueError("Structured profile entries require a resolved or partially resolved status.")
        if (self.resolution_status is StructuredResolutionStatus.RESOLVED) != self.record.has_minimum_trusted_identity:
            raise ValueError("Structured work entry status must match its minimum trusted identity.")
        return self


class StructuredEducationEntry(BaseModel):
    """Current provenance-aware education record state, without duplicating its resolution audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ResolvedEducation
    resolution_status: StructuredResolutionStatus
    candidate_id: str

    @model_validator(mode="after")
    def validate_admissible_status(self) -> "StructuredEducationEntry":
        if self.resolution_status not in _ADMISSIBLE_STATUSES:
            raise ValueError("Structured profile entries require a resolved or partially resolved status.")
        if (self.resolution_status is StructuredResolutionStatus.RESOLVED) != self.record.has_minimum_trusted_identity:
            raise ValueError("Structured education entry status must match its minimum trusted identity.")
        return self


class StructuredCareerProfile(BaseModel):
    """The current provenance-aware structured record layer; atomic facts remain in CareerProfile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_experiences: tuple[StructuredWorkExperienceEntry, ...] = Field(default_factory=tuple)
    education: tuple[StructuredEducationEntry, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_record_ids(self) -> "StructuredCareerProfile":
        for entries in (self.work_experiences, self.education):
            record_ids = tuple(entry.record.record_id for entry in entries)
            if len(record_ids) != len(set(record_ids)):
                raise ValueError("Structured profile record IDs must be unique within a collection.")
        return self


class SkippedStructuredRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: StructuredRecordType
    candidate_id: str
    record_id: str
    resolution_status: StructuredResolutionStatus
    reason_code: str


class StructuredRecordConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: StructuredRecordType
    record_id: str
    candidate_ids: tuple[str, ...]
    reason_code: str = "duplicate_record_id_conflicting_state"


class StructuredCareerProfileAssemblyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: StructuredCareerProfile
    applied_record_ids: tuple[str, ...] = Field(default_factory=tuple)
    skipped_records: tuple[SkippedStructuredRecord, ...] = Field(default_factory=tuple)
    conflicts: tuple[StructuredRecordConflict, ...] = Field(default_factory=tuple)

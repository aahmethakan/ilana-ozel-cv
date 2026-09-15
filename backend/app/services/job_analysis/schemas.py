from pydantic import BaseModel, ConfigDict, Field

from app.domain.job import JobProfile, JobRequirement, RequirementImportance


class UnresolvedJobItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_reference: str
    original_text: str
    reason_code: str


class JobImportanceConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    text: str
    importance_values: tuple[RequirementImportance, ...]
    source_references: tuple[str, ...]
    required_source_references: tuple[str, ...] = Field(default_factory=tuple)
    preferred_source_references: tuple[str, ...] = Field(default_factory=tuple)


class JobMetadataConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    selected_value: str
    source_value: str
    source_reference: str


class JobAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: JobProfile
    unresolved_items: tuple[UnresolvedJobItem, ...] = Field(default_factory=tuple)
    conflicts: tuple[JobImportanceConflict, ...] = Field(default_factory=tuple)
    metadata_conflicts: tuple[JobMetadataConflict, ...] = Field(default_factory=tuple)

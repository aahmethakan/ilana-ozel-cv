from pydantic import BaseModel, ConfigDict, Field

from app.domain.career import CareerFact, CareerProfile, FactSource


class SkippedCareerFact(BaseModel):
    """A trusted fact retained with the deterministic reason it was not applied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact: CareerFact
    reason_code: str


class ProfileAssemblyConflict(BaseModel):
    """A conflict that requires explicit future resolution instead of overwriting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_category: str
    existing_value: str
    incoming_value: str
    existing_source: FactSource
    incoming_source: FactSource
    reason_code: str


class CareerProfileAssemblyResult(BaseModel):
    """Pure, traceable result of merging trusted facts into a new profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: CareerProfile
    applied_facts: tuple[CareerFact, ...] = Field(default_factory=tuple)
    skipped_facts: tuple[SkippedCareerFact, ...] = Field(default_factory=tuple)
    conflicts: tuple[ProfileAssemblyConflict, ...] = Field(default_factory=tuple)

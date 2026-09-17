import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.claim_rendering import RenderedClaim


class SectionType(StrEnum):
    WORK_EXPERIENCE = "work_experience"
    EDUCATION = "education"


def _id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def work_entry_id(record_id: str, candidate_id: str, identity_id: str, date_id: str | None) -> str:
    return _id("work-entry", {"record_id": record_id, "candidate_id": candidate_id, "identity": identity_id, "date": date_id})


def education_entry_id(record_id: str, candidate_id: str, identity_id: str, date_id: str | None) -> str:
    return _id("education-entry", {"record_id": record_id, "candidate_id": candidate_id, "identity": identity_id, "date": date_id})


class ComposedWorkEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entry_id: str
    record_id: str
    candidate_id: str
    identity_claim: RenderedClaim
    date_claim: RenderedClaim | None = None

    @model_validator(mode="after")
    def validate_identity(self):
        claims = (self.identity_claim, self.date_claim) if self.date_claim else (self.identity_claim,)
        if self.identity_claim.rendering_mode.value != "work_identity" or any(claim.structured_lineage is None or claim.structured_lineage.record_type != "work" or (claim.structured_lineage.record_id, claim.structured_lineage.candidate_id) != (self.record_id, self.candidate_id) for claim in claims):
            raise ValueError("Work entry claims must have matching work lineage.")
        if self.date_claim and self.date_claim.rendering_mode.value != "work_date":
            raise ValueError("Work entry date claim must use work_date mode.")
        expected = work_entry_id(self.record_id, self.candidate_id, self.identity_claim.rendered_claim_id, self.date_claim.rendered_claim_id if self.date_claim else None)
        if self.entry_id != expected:
            raise ValueError("Work entry ID must match canonical content.")
        return self


class ComposedEducationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entry_id: str
    record_id: str
    candidate_id: str
    identity_claim: RenderedClaim
    date_claim: RenderedClaim | None = None

    @model_validator(mode="after")
    def validate_identity(self):
        claims = (self.identity_claim, self.date_claim) if self.date_claim else (self.identity_claim,)
        if self.identity_claim.rendering_mode.value != "education_identity" or any(claim.structured_lineage is None or claim.structured_lineage.record_type != "education" or (claim.structured_lineage.record_id, claim.structured_lineage.candidate_id) != (self.record_id, self.candidate_id) for claim in claims):
            raise ValueError("Education entry claims must have matching education lineage.")
        if self.date_claim and self.date_claim.rendering_mode.value != "education_date":
            raise ValueError("Education entry date claim must use education_date mode.")
        expected = education_entry_id(self.record_id, self.candidate_id, self.identity_claim.rendered_claim_id, self.date_claim.rendered_claim_id if self.date_claim else None)
        if self.entry_id != expected:
            raise ValueError("Education entry ID must match canonical content.")
        return self


Entry = ComposedWorkEntry | ComposedEducationEntry


def section_id(section_type: SectionType, entry_ids: tuple[str, ...]) -> str:
    return _id("section", {"section_type": section_type.value, "entry_ids": entry_ids})


class ComposedSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    section_id: str
    section_type: SectionType
    entries: tuple[Entry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity(self):
        expected_type = ComposedWorkEntry if self.section_type is SectionType.WORK_EXPERIENCE else ComposedEducationEntry
        if not all(isinstance(entry, expected_type) for entry in self.entries):
            raise ValueError("Section entries must match the declared section type.")
        ids = tuple(entry.entry_id for entry in self.entries)
        if len(set(ids)) != len(ids):
            raise ValueError("Composed sections cannot contain duplicate entries.")
        if self.section_id != section_id(self.section_type, ids):
            raise ValueError("Section ID must match ordered entries.")
        return self


class SectionCompositionErrorCode(StrEnum):
    MISSING_IDENTITY = "missing_identity"
    UNEXPECTED_RENDERING_MODE = "unexpected_rendering_mode"
    LINEAGE_MISMATCH = "lineage_mismatch"
    DUPLICATE_SLOT = "duplicate_slot"
    DUPLICATE_CLAIM = "duplicate_claim"
    DUPLICATE_ENTRY = "duplicate_entry"
    SECTION_TYPE_MISMATCH = "section_type_mismatch"


class SectionCompositionError(ValueError):
    def __init__(self, code: SectionCompositionErrorCode, message: str):
        self.code = code
        super().__init__(message)

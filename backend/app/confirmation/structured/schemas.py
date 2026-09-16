from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from app.confirmation.structured.identity import structured_candidate_id, structured_record_id
from app.domain.career import CareerDate, FactSource, ProvenancedBool, ProvenancedCareerDate, ProvenancedText

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
StructuredFieldValue = ProvenancedText | ProvenancedCareerDate | ProvenancedBool


class StructuredRecordType(StrEnum):
    WORK_EXPERIENCE = "work_experience"
    EDUCATION = "education"


class StructuredFieldAction(StrEnum):
    ACCEPT = "accept"
    CORRECT = "correct"
    REJECT = "reject"
    LEAVE_UNRESOLVED = "leave_unresolved"


class WholeRecordAction(StrEnum):
    REJECT_RECORD = "reject_record"


class StructuredResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    REJECTED = "rejected"
    INVALID = "invalid"


class StructuredRecordOrigin(BaseModel):
    """Stable, caller-provided origin for a proposed record without mutable field values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_sources: tuple[FactSource, ...] = Field(default_factory=tuple)
    origin_reference: NonEmptyText | None = None

    @model_validator(mode="after")
    def require_stable_origin(self) -> "StructuredRecordOrigin":
        if not self.evidence_sources and self.origin_reference is None:
            raise ValueError("A structured record requires evidence sources or an explicit stable origin reference.")
        return self

    def canonical_payload(self) -> dict[str, object]:
        sources_by_key = {
            json_key(item.model_dump(mode="json")): item.model_dump(mode="json")
            for item in self.evidence_sources
        }
        sources = [sources_by_key[key] for key in sorted(sources_by_key)]
        return {"evidence_sources": sources, "origin_reference": self.origin_reference}


def json_key(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class TextFieldDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: StructuredFieldAction
    corrected_value: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> "TextFieldDecision":
        if (self.action is StructuredFieldAction.CORRECT) != (self.corrected_value is not None):
            raise ValueError("Text CORRECT decisions require a value and other actions must not provide one.")
        return self


class CareerDateFieldDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: StructuredFieldAction
    corrected_value: CareerDate | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> "CareerDateFieldDecision":
        if (self.action is StructuredFieldAction.CORRECT) != (self.corrected_value is not None):
            raise ValueError("CareerDate CORRECT decisions require a value and other actions must not provide one.")
        return self


class BoolFieldDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: StructuredFieldAction
    corrected_value: StrictBool | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> "BoolFieldDecision":
        if (self.action is StructuredFieldAction.CORRECT) != (self.corrected_value is not None):
            raise ValueError("Bool CORRECT decisions require a value and other actions must not provide one.")
        return self


class WorkExperienceFieldDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company: TextFieldDecision | None = None
    title: TextFieldDecision | None = None
    location: TextFieldDecision | None = None
    start_date: CareerDateFieldDecision | None = None
    end_date: CareerDateFieldDecision | None = None
    is_current: BoolFieldDecision | None = None


class EducationFieldDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    institution: TextFieldDecision | None = None
    degree: TextFieldDecision | None = None
    field_of_study: TextFieldDecision | None = None
    start_date: CareerDateFieldDecision | None = None
    end_date: CareerDateFieldDecision | None = None


class WorkExperienceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal[StructuredRecordType.WORK_EXPERIENCE] = StructuredRecordType.WORK_EXPERIENCE
    origin: StructuredRecordOrigin
    company: ProvenancedText | None = None
    title: ProvenancedText | None = None
    location: ProvenancedText | None = None
    start_date: ProvenancedCareerDate | None = None
    end_date: ProvenancedCareerDate | None = None
    is_current: ProvenancedBool | None = None
    record_id: str
    candidate_id: str

    @model_validator(mode="after")
    def validate_identity(self) -> "WorkExperienceCandidate":
        _validate_candidate_identity(self)
        return self


class EducationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal[StructuredRecordType.EDUCATION] = StructuredRecordType.EDUCATION
    origin: StructuredRecordOrigin
    institution: ProvenancedText | None = None
    degree: ProvenancedText | None = None
    field_of_study: ProvenancedText | None = None
    start_date: ProvenancedCareerDate | None = None
    end_date: ProvenancedCareerDate | None = None
    record_id: str
    candidate_id: str

    @model_validator(mode="after")
    def validate_identity(self) -> "EducationCandidate":
        _validate_candidate_identity(self)
        return self


def _candidate_payload(candidate: WorkExperienceCandidate | EducationCandidate) -> dict[str, object]:
    data = candidate.model_dump(mode="json", exclude={"record_id", "candidate_id"})
    return data


def _validate_candidate_identity(candidate: WorkExperienceCandidate | EducationCandidate) -> None:
    expected_record_id = structured_record_id(candidate.record_type.value, candidate.origin.canonical_payload())
    if candidate.record_id != expected_record_id:
        raise ValueError("record_id does not match the candidate origin.")
    expected_candidate_id = structured_candidate_id(candidate.record_id, _candidate_payload(candidate))
    if candidate.candidate_id != expected_candidate_id:
        raise ValueError("candidate_id does not match the candidate proposal.")


def create_work_experience_candidate(*, origin: StructuredRecordOrigin, company: ProvenancedText | None = None, title: ProvenancedText | None = None, location: ProvenancedText | None = None, start_date: ProvenancedCareerDate | None = None, end_date: ProvenancedCareerDate | None = None, is_current: ProvenancedBool | None = None) -> WorkExperienceCandidate:
    record_id = structured_record_id(StructuredRecordType.WORK_EXPERIENCE.value, origin.canonical_payload())
    data = {"origin": origin, "company": company, "title": title, "location": location, "start_date": start_date, "end_date": end_date, "is_current": is_current, "record_id": record_id}
    candidate_id = structured_candidate_id(record_id, {
        "record_type": StructuredRecordType.WORK_EXPERIENCE.value,
        "origin": origin.model_dump(mode="json"),
        **{name: value.model_dump(mode="json") if value is not None else None for name, value in data.items() if name not in {"origin", "record_id"}},
    })
    return WorkExperienceCandidate(candidate_id=candidate_id, **data)


def create_education_candidate(*, origin: StructuredRecordOrigin, institution: ProvenancedText | None = None, degree: ProvenancedText | None = None, field_of_study: ProvenancedText | None = None, start_date: ProvenancedCareerDate | None = None, end_date: ProvenancedCareerDate | None = None) -> EducationCandidate:
    record_id = structured_record_id(StructuredRecordType.EDUCATION.value, origin.canonical_payload())
    data = {"origin": origin, "institution": institution, "degree": degree, "field_of_study": field_of_study, "start_date": start_date, "end_date": end_date, "record_id": record_id}
    candidate_id = structured_candidate_id(record_id, {
        "record_type": StructuredRecordType.EDUCATION.value,
        "origin": origin.model_dump(mode="json"),
        **{name: value.model_dump(mode="json") if value is not None else None for name, value in data.items() if name not in {"origin", "record_id"}},
    })
    return EducationCandidate(candidate_id=candidate_id, **data)


class ResolvedWorkExperience(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str
    company: ProvenancedText | None = None
    title: ProvenancedText | None = None
    location: ProvenancedText | None = None
    start_date: ProvenancedCareerDate | None = None
    end_date: ProvenancedCareerDate | None = None
    is_current: ProvenancedBool | None = None

    @property
    def has_minimum_trusted_identity(self) -> bool:
        return bool(self.company and self.company.is_claim_usable and self.title and self.title.is_claim_usable)


class ResolvedEducation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str
    institution: ProvenancedText | None = None
    degree: ProvenancedText | None = None
    field_of_study: ProvenancedText | None = None
    start_date: ProvenancedCareerDate | None = None
    end_date: ProvenancedCareerDate | None = None

    @property
    def has_minimum_trusted_identity(self) -> bool:
        return bool(self.institution and self.institution.is_claim_usable and ((self.degree and self.degree.is_claim_usable) or (self.field_of_study and self.field_of_study.is_claim_usable)))


class StructuredFieldResolutionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str
    action: StructuredFieldAction | None = None
    original_proposed_value: StructuredFieldValue | None = None
    corrected_value: str | CareerDate | bool | None = None
    resolved_value: StructuredFieldValue | None = None


class StructuredRecordResolutionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    record_id: str
    record_type: StructuredRecordType
    origin: StructuredRecordOrigin
    whole_record_action: WholeRecordAction | None = None
    field_audits: tuple[StructuredFieldResolutionAudit, ...] = Field(default_factory=tuple)


class WorkExperienceResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: WorkExperienceCandidate
    status: StructuredResolutionStatus
    audit: StructuredRecordResolutionAudit
    resolved_record: ResolvedWorkExperience | None = None
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)


class EducationResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: EducationCandidate
    status: StructuredResolutionStatus
    audit: StructuredRecordResolutionAudit
    resolved_record: ResolvedEducation | None = None
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)

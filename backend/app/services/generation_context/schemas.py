import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.career import ContactValue, FactSource, ProvenancedBool, ProvenancedCareerDate, ProvenancedText, VerificationStatus


def atomic_evidence_id(*, claim_type: str, statement: str, verification_status: VerificationStatus, source: FactSource) -> str:
    payload = {"claim_type": claim_type, "statement": statement, "verification_status": verification_status.value, "source": source.model_dump(mode="json")}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"atomic:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class EligibleAtomicClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    claim_type: str
    statement: str
    verification_status: VerificationStatus
    source: FactSource

    @model_validator(mode="after")
    def validate_identity_and_eligibility(self) -> "EligibleAtomicClaim":
        if self.verification_status is VerificationStatus.INFERRED_UNVERIFIED:
            raise ValueError("Inferred atomic claims are not generation eligible.")
        if self.evidence_id != atomic_evidence_id(claim_type=self.claim_type, statement=self.statement, verification_status=self.verification_status, source=self.source):
            raise ValueError("Eligible atomic claim evidence ID must match its canonical content.")
        return self


class EligibleContact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    email: "EligibleContactField | None" = None
    phone: "EligibleContactField | None" = None
    website: "EligibleContactField | None" = None


def contact_field_evidence_id(*, field_name: str, value: ContactValue) -> str:
    payload = {"field_name": field_name, "value": value.model_dump(mode="json")}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"contact-field:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class EligibleContactField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    field_name: Literal["email", "phone", "website"]
    value: ContactValue

    @model_validator(mode="after")
    def validate_identity(self) -> "EligibleContactField":
        if self.evidence_id != contact_field_evidence_id(field_name=self.field_name, value=self.value):
            raise ValueError("Eligible contact field requires its canonical evidence ID.")
        return self


EligibleValue = ProvenancedText | ProvenancedCareerDate | ProvenancedBool


def structured_field_evidence_id(*, record_type: str, record_id: str, candidate_id: str, field_name: str, value: EligibleValue) -> str:
    payload = {"record_type": record_type, "record_id": record_id, "candidate_id": candidate_id, "field_name": field_name, "value": value.model_dump(mode="json")}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{record_type}-field:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class EligibleStructuredField(BaseModel):
    """One current, usable structured value; no proposed, rejected, or alternative value is retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    record_type: str
    record_id: str
    candidate_id: str
    field_name: str
    value: EligibleValue

    @model_validator(mode="after")
    def validate_identity_and_usability(self) -> "EligibleStructuredField":
        if not self.value.is_claim_usable or self.evidence_id != structured_field_evidence_id(record_type=self.record_type, record_id=self.record_id, candidate_id=self.candidate_id, field_name=self.field_name, value=self.value):
            raise ValueError("Eligible structured field requires a usable value and canonical evidence ID.")
        return self


class EligibleWorkExperience(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    record_id: str
    candidate_id: str
    company: EligibleStructuredField
    title: EligibleStructuredField
    location: EligibleStructuredField | None = None
    start_date: EligibleStructuredField | None = None
    end_date: EligibleStructuredField | None = None
    is_current: EligibleStructuredField | None = None

    @model_validator(mode="after")
    def validate_usable_identity(self) -> "EligibleWorkExperience":
        if self.evidence_id != f"work:{self.record_id}" or self.company.field_name != "company" or self.title.field_name != "title":
            raise ValueError("Eligible work experience requires its deterministic record ID and usable identity.")
        return self


class EligibleEducation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    record_id: str
    candidate_id: str
    institution: EligibleStructuredField
    degree: EligibleStructuredField | None = None
    field_of_study: EligibleStructuredField | None = None
    start_date: EligibleStructuredField | None = None
    end_date: EligibleStructuredField | None = None

    @model_validator(mode="after")
    def validate_usable_identity(self) -> "EligibleEducation":
        if self.evidence_id != f"education:{self.record_id}" or self.institution.field_name != "institution" or not (self.degree or self.field_of_study):
            raise ValueError("Eligible education requires its deterministic record ID and usable identity.")
        return self


class GenerationContext(BaseModel):
    """Generation-safe evidence projection; it intentionally excludes raw unresolved and rejected data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contact: EligibleContact | None = None
    atomic_claims: tuple[EligibleAtomicClaim, ...] = Field(default_factory=tuple)
    work_experiences: tuple[EligibleWorkExperience, ...] = Field(default_factory=tuple)
    education: tuple[EligibleEducation, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_evidence_ids_are_unique(self) -> "GenerationContext":
        evidence = list(self.atomic_claims)
        if self.contact:
            evidence.extend(value for value in (self.contact.email, self.contact.phone, self.contact.website) if value is not None)
        for record in (*self.work_experiences, *self.education):
            values = (record.company, record.title, record.location, record.start_date, record.end_date, record.is_current) if isinstance(record, EligibleWorkExperience) else (record.institution, record.degree, record.field_of_study, record.start_date, record.end_date)
            evidence.extend(value for value in values if value is not None)
        ids = [item.evidence_id for item in evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Generation evidence IDs must be unique.")
        return self

    def find_eligible_evidence(self, evidence_id: str) -> EligibleAtomicClaim | EligibleStructuredField | EligibleContactField | None:
        for item in self.atomic_claims:
            if item.evidence_id == evidence_id:
                return item
        if self.contact:
            for value in (self.contact.email, self.contact.phone, self.contact.website):
                if value is not None and value.evidence_id == evidence_id:
                    return value
        for record in (*self.work_experiences, *self.education):
            values = (record.company, record.title, record.location, record.start_date, record.end_date, record.is_current) if isinstance(record, EligibleWorkExperience) else (record.institution, record.degree, record.field_of_study, record.start_date, record.end_date)
            for value in values:
                if isinstance(value, EligibleStructuredField) and value.evidence_id == evidence_id:
                    return value
        return None

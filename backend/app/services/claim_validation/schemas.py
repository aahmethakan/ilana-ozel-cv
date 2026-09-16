import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.domain.career import CareerDate
from app.services.evidence_convergence.schemas import EducationField, WorkExperienceField


class ClaimKind(StrEnum):
    SUMMARY = "summary"
    EXPERIENCE_BULLET = "experience_bullet"
    EDUCATION = "education"
    SKILL = "skill"
    OTHER = "other"


class AtomicClaimAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_kind: Literal["atomic"] = "atomic"
    evidence_id: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    value: str = Field(min_length=1)


class WorkFieldAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_kind: Literal["work_field"] = "work_field"
    evidence_id: str = Field(min_length=1)
    record_type: Literal["work"] = "work"
    record_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    field_name: WorkExperienceField
    value: str | CareerDate | StrictBool

    @model_validator(mode="after")
    def validate_field_value_type(self) -> "WorkFieldAssertion":
        if self.field_name is WorkExperienceField.IS_CURRENT:
            valid = type(self.value) is bool
        elif self.field_name in {WorkExperienceField.START_DATE, WorkExperienceField.END_DATE}:
            valid = isinstance(self.value, CareerDate)
        else:
            valid = type(self.value) is str
        if not valid:
            raise ValueError("Work assertion value must use the field's exact value type.")
        return self


class EducationFieldAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_kind: Literal["education_field"] = "education_field"
    evidence_id: str = Field(min_length=1)
    record_type: Literal["education"] = "education"
    record_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    field_name: EducationField
    value: str | CareerDate

    @model_validator(mode="after")
    def validate_field_value_type(self) -> "EducationFieldAssertion":
        if self.field_name in {EducationField.START_DATE, EducationField.END_DATE}:
            valid = isinstance(self.value, CareerDate)
        else:
            valid = type(self.value) is str
        if not valid:
            raise ValueError("Education assertion value must use the field's exact value type.")
        return self


class ContactFieldAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_kind: Literal["contact_field"] = "contact_field"
    evidence_id: str = Field(min_length=1)
    field_name: Literal["email", "phone", "website"]
    value: str = Field(min_length=1)


Assertion = Annotated[
    AtomicClaimAssertion | WorkFieldAssertion | EducationFieldAssertion | ContactFieldAssertion,
    Field(discriminator="assertion_kind"),
]


def claim_id(*, claim_kind: ClaimKind, text: str, assertions: tuple[Assertion, ...]) -> str:
    """Create a deterministic ID from the declared assertion set, independent of order."""

    payload = {
        "claim_kind": claim_kind.value,
        "text": text,
        "assertions": sorted(
            (item.model_dump(mode="json") for item in assertions),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"claim:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class GeneratedClaimProposal(BaseModel):
    """A proposed claim with declarative evidence assertions only.

    A VALID result establishes only that each assertion exactly matches eligible
    evidence. It does not verify the whole prose claim, establish factual truth,
    or make the text safe to export.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    claim_kind: ClaimKind
    assertions: tuple[Assertion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity(self) -> "GeneratedClaimProposal":
        if not self.text.strip():
            raise ValueError("Claim text must not be blank.")
        encoded_assertions = {
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            for item in self.assertions
        }
        if len(encoded_assertions) != len(self.assertions):
            raise ValueError("Claims cannot contain duplicate assertions.")
        if self.claim_id != claim_id(claim_kind=self.claim_kind, text=self.text, assertions=self.assertions):
            raise ValueError("Claim ID must match canonical claim content.")
        return self

    @property
    def supporting_evidence_ids(self) -> tuple[str, ...]:
        """Derived aggregate only; callers cannot separately authorize evidence."""

        return tuple(sorted({item.evidence_id for item in self.assertions}))


class ClaimValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class ClaimValidationFindingCode(StrEnum):
    UNKNOWN_EVIDENCE = "unknown_evidence"
    EVIDENCE_KIND_MISMATCH = "evidence_kind_mismatch"
    LINEAGE_MISMATCH = "lineage_mismatch"
    FIELD_MISMATCH = "field_mismatch"
    VALUE_MISMATCH = "value_mismatch"


class ClaimValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ClaimValidationFindingCode
    assertion_index: int = Field(ge=0)
    evidence_id: str | None = None


class ClaimValidationResult(BaseModel):
    """Assertion-match result only; it deliberately has no truth or export-safety flag."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    status: ClaimValidationStatus
    findings: tuple[ClaimValidationFinding, ...] = ()

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.career.enums import SourceType, VerificationStatus
from app.domain.career.source import FactSource


def _identity(prefix: str, payload: dict) -> str:
    return f"{prefix}:{hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}"


def _validate_canonical_endpoint_identifier(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("Association endpoint identifiers must be nonblank and free of outer whitespace.")
    return value


def work_fact_association_candidate_id(*, atomic_evidence_id: str, work_record_id: str, work_candidate_id: str, source: FactSource) -> str:
    return _identity("work-fact-association-candidate", {"atomic_evidence_id": atomic_evidence_id, "work_record_id": work_record_id, "work_candidate_id": work_candidate_id, "source": source.model_dump(mode="json")})


def work_fact_association_id(*, atomic_evidence_id: str, work_record_id: str, work_candidate_id: str, verification_status: VerificationStatus, source: FactSource) -> str:
    return _identity("work-fact-association", {"atomic_evidence_id": atomic_evidence_id, "work_record_id": work_record_id, "work_candidate_id": work_candidate_id, "verification_status": verification_status.value, "source": source.model_dump(mode="json")})


class WorkFactAssociationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_id: str
    atomic_evidence_id: str = Field(min_length=1)
    work_record_id: str = Field(min_length=1)
    work_candidate_id: str = Field(min_length=1)
    verification_status: VerificationStatus
    source: FactSource

    @field_validator("atomic_evidence_id", "work_record_id", "work_candidate_id")
    @classmethod
    def validate_canonical_endpoint_identifiers(cls, value: str) -> str:
        return _validate_canonical_endpoint_identifier(value)

    @model_validator(mode="after")
    def validate_identity_and_trust(self):
        if self.verification_status is not VerificationStatus.INFERRED_UNVERIFIED:
            raise ValueError("Work-fact association candidates must remain unverified until explicit confirmation.")
        if self.candidate_id != work_fact_association_candidate_id(atomic_evidence_id=self.atomic_evidence_id, work_record_id=self.work_record_id, work_candidate_id=self.work_candidate_id, source=self.source):
            raise ValueError("Association candidate ID must match canonical content.")
        return self


class WorkFactAssociation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    association_id: str
    atomic_evidence_id: str = Field(min_length=1)
    work_record_id: str = Field(min_length=1)
    work_candidate_id: str = Field(min_length=1)
    verification_status: VerificationStatus
    source: FactSource

    @field_validator("atomic_evidence_id", "work_record_id", "work_candidate_id")
    @classmethod
    def validate_canonical_endpoint_identifiers(cls, value: str) -> str:
        return _validate_canonical_endpoint_identifier(value)

    @model_validator(mode="after")
    def validate_identity_and_trust(self):
        if (
            self.source.source_type is not SourceType.USER_INPUT
            or self.verification_status is not VerificationStatus.USER_PROVIDED
        ):
            raise ValueError(
                "Trusted work-fact associations require USER_INPUT source and USER_PROVIDED status."
            )
        if self.association_id != work_fact_association_id(atomic_evidence_id=self.atomic_evidence_id, work_record_id=self.work_record_id, work_candidate_id=self.work_candidate_id, verification_status=self.verification_status, source=self.source):
            raise ValueError("Association ID must match canonical trusted relationship.")
        return self

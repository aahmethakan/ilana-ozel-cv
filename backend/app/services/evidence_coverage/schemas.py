import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.confirmation.structured.schemas import StructuredRecordType
from app.extraction.career import UnresolvedEvidence
from app.services.evidence_convergence.schemas import (
    EducationField,
    EvidenceConvergenceState,
    WorkExperienceField,
)


class EvidenceCoverageStatus(StrEnum):
    DECLARED_COMPLETE = "declared_complete"
    DECLARED_PARTIAL = "declared_partial"


class EvidenceCoverageOverallState(StrEnum):
    COMPLETE_AND_CLOSED = "complete_and_closed"
    COMPLETE_BUT_OPEN = "complete_but_open"
    PARTIAL = "partial"
    UNDECLARED = "undeclared"


_WORK_FIELD_ORDER = ("company", "title", "location", "start_date", "end_date", "is_current")
_EDUCATION_FIELD_ORDER = ("institution", "degree", "field_of_study", "start_date", "end_date")


def canonical_coverage_fields(record_type: StructuredRecordType, fields: tuple[WorkExperienceField | EducationField, ...]) -> tuple[WorkExperienceField | EducationField, ...]:
    order = _WORK_FIELD_ORDER if record_type is StructuredRecordType.WORK_EXPERIENCE else _EDUCATION_FIELD_ORDER
    return tuple(sorted(fields, key=lambda field: order.index(field.value)))


def computed_coverage_id(*, evidence_key: str, record_type: StructuredRecordType, record_id: str, candidate_id: str, covered_fields: tuple[WorkExperienceField | EducationField, ...], coverage_status: "EvidenceCoverageStatus") -> str:
    payload = {
        "evidence_key": evidence_key,
        "record_type": record_type.value,
        "record_id": record_id,
        "candidate_id": candidate_id,
        "covered_fields": [field.value for field in canonical_coverage_fields(record_type, covered_fields)],
        "coverage_status": coverage_status.value,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"coverage:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class WorkEvidenceCoverageDeclaration(BaseModel):
    """Producer metadata for structured mapping scope, never a claim about whole-source understanding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_key: str
    record_type: Literal[StructuredRecordType.WORK_EXPERIENCE] = StructuredRecordType.WORK_EXPERIENCE
    record_id: str
    candidate_id: str
    covered_fields: tuple[WorkExperienceField, ...]
    coverage_status: EvidenceCoverageStatus

    @model_validator(mode="after")
    def validate_covered_fields(self) -> "WorkEvidenceCoverageDeclaration":
        if not self.covered_fields:
            raise ValueError("Evidence coverage declarations require at least one covered field.")
        if len(self.covered_fields) != len(set(self.covered_fields)):
            raise ValueError("Evidence coverage declarations cannot repeat a covered field.")
        return self


class EducationEvidenceCoverageDeclaration(BaseModel):
    """Producer metadata for structured mapping scope, never a claim about whole-source understanding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_key: str
    record_type: Literal[StructuredRecordType.EDUCATION] = StructuredRecordType.EDUCATION
    record_id: str
    candidate_id: str
    covered_fields: tuple[EducationField, ...]
    coverage_status: EvidenceCoverageStatus

    @model_validator(mode="after")
    def validate_covered_fields(self) -> "EducationEvidenceCoverageDeclaration":
        if not self.covered_fields:
            raise ValueError("Evidence coverage declarations require at least one covered field.")
        if len(self.covered_fields) != len(set(self.covered_fields)):
            raise ValueError("Evidence coverage declarations cannot repeat a covered field.")
        return self


EvidenceCoverageDeclaration = WorkEvidenceCoverageDeclaration | EducationEvidenceCoverageDeclaration


class EvidenceCoverageFieldState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: WorkExperienceField | EducationField
    convergence_state: EvidenceConvergenceState


class EvidenceCoverageItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    coverage_id: str | None = None
    evidence_key: str
    record_type: StructuredRecordType
    record_id: str
    candidate_id: str
    covered_fields: tuple[WorkExperienceField | EducationField, ...]
    coverage_status: EvidenceCoverageStatus | None = None
    field_states: tuple[EvidenceCoverageFieldState, ...]
    overall_state: EvidenceCoverageOverallState

    @model_validator(mode="after")
    def validate_consistency(self) -> "EvidenceCoverageItem":
        fields = self.covered_fields
        allowed = _WORK_FIELD_ORDER if self.record_type is StructuredRecordType.WORK_EXPERIENCE else _EDUCATION_FIELD_ORDER
        if not fields or len(fields) != len(set(fields)) or any(field.value not in allowed for field in fields):
            raise ValueError("Coverage item fields must be unique and valid for its record type.")
        if tuple(state.field_name for state in self.field_states) != canonical_coverage_fields(self.record_type, fields):
            raise ValueError("Coverage item field snapshots must exactly and canonically match covered fields.")
        if self.coverage_status is None:
            if self.coverage_id is not None or self.overall_state is not EvidenceCoverageOverallState.UNDECLARED:
                raise ValueError("Undeclared coverage items cannot have a coverage ID or declared overall state.")
            return self
        expected_id = computed_coverage_id(
            evidence_key=self.evidence_key, record_type=self.record_type, record_id=self.record_id,
            candidate_id=self.candidate_id, covered_fields=fields, coverage_status=self.coverage_status,
        )
        if self.coverage_id != expected_id:
            raise ValueError("Coverage item ID must match its declaration metadata.")
        allowed_states = {
            EvidenceCoverageStatus.DECLARED_COMPLETE: {
                EvidenceCoverageOverallState.COMPLETE_AND_CLOSED,
                EvidenceCoverageOverallState.COMPLETE_BUT_OPEN,
            },
            EvidenceCoverageStatus.DECLARED_PARTIAL: {EvidenceCoverageOverallState.PARTIAL},
        }
        if self.overall_state not in allowed_states[self.coverage_status]:
            raise ValueError("Coverage item overall state must match its declaration status.")
        return self


class EvidenceCoverageResult(BaseModel):
    """Structured binding coverage only; it deliberately makes no whole-source closure claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[EvidenceCoverageItem, ...] = Field(default_factory=tuple)
    unbound_unresolved_evidence: tuple[UnresolvedEvidence, ...] = Field(default_factory=tuple)

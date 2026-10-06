import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.claim_validation import ClaimKind


class ClaimRenderingMode(StrEnum):
    ATOMIC_EXACT = "atomic_exact"
    CONTACT_EXACT = "contact_exact"
    WORK_IDENTITY = "work_identity"
    WORK_DATE = "work_date"
    EDUCATION_IDENTITY = "education_identity"
    EDUCATION_DATE = "education_date"
    WORK_FACT_EXACT = "work_fact_exact"


def rendered_claim_id(
    *,
    rendering_mode: ClaimRenderingMode,
    text: str,
    source_claim_id: str,
    supporting_evidence_ids: tuple[str, ...],
    structured_lineage: "StructuredClaimLineage | None" = None,
) -> str:
    payload = {
        "rendering_mode": rendering_mode.value,
        "text": text,
        "supporting_evidence_ids": tuple(sorted(supporting_evidence_ids)),
        "structured_lineage": structured_lineage.model_dump(mode="json") if structured_lineage else None,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"rendered-claim:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


class RenderedClaim(BaseModel):
    """A deterministic rendering of an entirely consumed, validated assertion set.

    This is deliberately narrower than a final or export-safe CV claim: it makes
    no statement about document completeness, strategy, or prose semantics.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rendered_claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    claim_kind: ClaimKind
    source_claim_id: str = Field(min_length=1)
    supporting_evidence_ids: tuple[str, ...] = Field(min_length=1)
    rendering_mode: ClaimRenderingMode
    structured_lineage: "StructuredClaimLineage | None" = None

    @model_validator(mode="after")
    def validate_identity(self) -> "RenderedClaim":
        if len(set(self.supporting_evidence_ids)) != len(self.supporting_evidence_ids):
            raise ValueError("Rendered claims cannot contain duplicate supporting evidence IDs.")
        if tuple(sorted(self.supporting_evidence_ids)) != self.supporting_evidence_ids:
            raise ValueError("Rendered claim evidence IDs must be canonically ordered.")
        expected_id = rendered_claim_id(
            rendering_mode=self.rendering_mode,
            text=self.text,
            source_claim_id=self.source_claim_id,
            supporting_evidence_ids=self.supporting_evidence_ids,
            structured_lineage=self.structured_lineage,
        )
        if self.rendered_claim_id != expected_id:
            raise ValueError("Rendered claim ID must match canonical rendered content.")
        return self


class StructuredClaimLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal["work", "education"]
    record_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)


class ClaimRenderingErrorCode(StrEnum):
    CLAIM_VALIDATION_FAILED = "claim_validation_failed"
    ASSERTION_SET_MISMATCH = "assertion_set_mismatch"
    LINEAGE_MISMATCH = "lineage_mismatch"
    MISSING_REQUIRED_ASSERTION = "missing_required_assertion"
    UNEXPECTED_ASSERTION = "unexpected_assertion"
    UNSUPPORTED_FIELD_COMBINATION = "unsupported_field_combination"


class ClaimNotRenderableError(ValueError):
    """A deterministic, fail-closed rendering error with a machine-readable code."""

    def __init__(self, code: ClaimRenderingErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)

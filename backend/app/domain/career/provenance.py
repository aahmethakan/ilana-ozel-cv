from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain.career.dates import CareerDate
from app.domain.career.enums import SourceType, VerificationStatus
from app.domain.career.source import FactSource

T = TypeVar("T")
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_USABLE_STATUSES = frozenset({VerificationStatus.VERIFIED, VerificationStatus.USER_PROVIDED})


def is_verification_usable(status: VerificationStatus) -> bool:
    """Central trust policy for whether a value may be rendered as a factual claim."""

    return status in _USABLE_STATUSES


class ProvenancedValue(BaseModel, Generic[T]):
    """A typed value with explicit verification and both current-value and supporting provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: T
    verification_status: VerificationStatus
    value_source: FactSource
    evidence_sources: tuple[FactSource, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_source_consistency(self) -> "ProvenancedValue[T]":
        if self.value_source.source_type is SourceType.USER_INPUT and self.verification_status is not VerificationStatus.USER_PROVIDED:
            raise ValueError("USER_INPUT values must be USER_PROVIDED.")
        if self.value_source.source_type is SourceType.SYSTEM_INFERENCE and self.verification_status is not VerificationStatus.INFERRED_UNVERIFIED:
            raise ValueError("SYSTEM_INFERENCE values must be INFERRED_UNVERIFIED.")
        return self

    @property
    def is_claim_usable(self) -> bool:
        return is_verification_usable(self.verification_status)


ProvenancedText = ProvenancedValue[NonEmptyText]
ProvenancedCareerDate = ProvenancedValue[CareerDate]
ProvenancedBool = ProvenancedValue[bool]

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain.career.enums import VerificationStatus
from app.domain.career.source import FactSource

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MetricValue = int | float


class Metric(BaseModel):
    """A quantified component of a career fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: MetricValue
    unit: NonEmptyText | None = None
    label: NonEmptyText | None = None


class CareerFact(BaseModel):
    """A career claim with provenance and a generation-safety state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: NonEmptyText
    verification_status: VerificationStatus
    source: FactSource
    skills: tuple[NonEmptyText, ...] = Field(default_factory=tuple)
    language: NonEmptyText | None = None
    language_proficiency: NonEmptyText | None = None
    tools: tuple[NonEmptyText, ...] = Field(default_factory=tuple)
    certifications: tuple[NonEmptyText, ...] = Field(default_factory=tuple)
    metrics: tuple[Metric, ...] = Field(default_factory=tuple)
    action: NonEmptyText | None = None
    object: NonEmptyText | None = None
    result: NonEmptyText | None = None
    context: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_language_fields(self) -> "CareerFact":
        if self.language is None and self.language_proficiency is not None:
            raise ValueError("Language proficiency requires an explicit language.")
        return self

    @property
    def is_claim_usable(self) -> bool:
        """Whether this fact may be used as a factual generated-CV claim."""

        return self.verification_status in {
            VerificationStatus.VERIFIED,
            VerificationStatus.USER_PROVIDED,
        }

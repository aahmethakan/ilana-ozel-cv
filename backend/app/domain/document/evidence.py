from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.document.location import NonEmptyText


class ParserConfidence(StrEnum):
    """How certain deterministic document parsing is about a classification."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNRESOLVED = "unresolved"


class IdentityField(StrEnum):
    NAME = "name"
    HEADLINE = "headline"
    EMAIL = "email"
    PHONE = "phone"
    WEBSITE = "website"


class IdentityEvidence(BaseModel):
    """A parser observation, deliberately separate from a career claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: IdentityField
    value: NonEmptyText
    block_reference: NonEmptyText
    confidence: ParserConfidence
    reason: NonEmptyText

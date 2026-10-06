from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.document.enums import BlockType, SectionType
from app.domain.document.evidence import ParserConfidence
from app.domain.document.location import NonEmptyText, SourceLocation


class DocumentBlock(BaseModel):
    """One canonical, unmodified piece of source-document text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_text: str
    block_type: BlockType
    location: SourceLocation

    @field_validator("raw_text")
    @classmethod
    def raw_text_must_contain_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Raw block text cannot be blank.")
        return value

    @property
    def stable_reference(self) -> str:
        return self.location.stable_reference


class CVSection(BaseModel):
    """A classified view of canonical blocks, retaining the original heading."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    section_type: SectionType
    original_heading: NonEmptyText | None = None
    block_references: tuple[NonEmptyText, ...] = Field(default_factory=tuple)
    confidence: ParserConfidence = ParserConfidence.HIGH


class DocumentPage(BaseModel):
    """An ordered page view that references canonical document blocks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    block_references: tuple[NonEmptyText, ...] = Field(default_factory=tuple)

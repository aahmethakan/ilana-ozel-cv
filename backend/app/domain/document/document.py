from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain.document.blocks import CVSection, DocumentBlock, DocumentPage
from app.domain.document.enums import DocumentFormat

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DocumentSource(BaseModel):
    """Non-path metadata describing an uploaded source document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: NonEmptyText
    document_format: DocumentFormat
    media_type: NonEmptyText | None = None
    page_count: int | None = Field(default=None, ge=1)


class CVDocument(BaseModel):
    """Immutable source evidence from a parsed CV, without normalized career facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: DocumentSource
    blocks: tuple[DocumentBlock, ...] = Field(default_factory=tuple)
    pages: tuple[DocumentPage, ...] = Field(default_factory=tuple)
    sections: tuple[CVSection, ...] = Field(default_factory=tuple)
    detected_languages: tuple[NonEmptyText, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_document_references(self) -> "CVDocument":
        block_references = tuple(block.stable_reference for block in self.blocks)
        if len(block_references) != len(set(block_references)):
            raise ValueError("Canonical block references must be unique within a document.")

        known_references = set(block_references)
        blocks_by_reference = {block.stable_reference: block for block in self.blocks}

        page_numbers = tuple(page.page_number for page in self.pages)
        if page_numbers != tuple(sorted(page_numbers)) or len(page_numbers) != len(set(page_numbers)):
            raise ValueError("Document pages must have unique ascending page numbers.")

        if self.source.page_count is not None:
            expected_page_numbers = tuple(range(1, self.source.page_count + 1))
            if page_numbers != expected_page_numbers:
                raise ValueError("Pages must match the known document page count.")

        page_references: set[str] = set()
        for page in self.pages:
            if len(page.block_references) != len(set(page.block_references)):
                raise ValueError("A page cannot reference the same block more than once.")
            for reference in page.block_references:
                if reference not in known_references:
                    raise ValueError("Page references an unknown canonical block.")
                if blocks_by_reference[reference].location.page_number != page.page_number:
                    raise ValueError("Page references a block from a different page.")
                if reference in page_references:
                    raise ValueError("A canonical block cannot belong to multiple pages.")
                page_references.add(reference)

        for block in self.blocks:
            if block.location.page_number is not None and block.stable_reference not in page_references:
                raise ValueError("A page-located block must be referenced by its page.")

        section_references: set[str] = set()
        for section in self.sections:
            if len(section.block_references) != len(set(section.block_references)):
                raise ValueError("A section cannot reference the same block more than once.")
            for reference in section.block_references:
                if reference not in known_references:
                    raise ValueError("Section references an unknown canonical block.")
                if reference in section_references:
                    raise ValueError("A canonical block cannot belong to multiple sections.")
                section_references.add(reference)

        return self

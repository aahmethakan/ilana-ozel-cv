from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SourceLocation(BaseModel):
    """Location of one canonical block in the parsed source document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int | None = Field(default=None, ge=1)
    block_index: int = Field(ge=0)
    section_hint: NonEmptyText | None = None
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> "SourceLocation":
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("End offset cannot be before start offset.")
        return self

    @property
    def stable_reference(self) -> str:
        if self.page_number is None:
            return f"document:block:{self.block_index}"
        return f"page:{self.page_number}:block:{self.block_index}"

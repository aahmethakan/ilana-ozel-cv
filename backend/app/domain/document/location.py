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
    x0: float | None = Field(default=None, ge=0)
    y0: float | None = Field(default=None, ge=0)
    x1: float | None = Field(default=None, ge=0)
    y1: float | None = Field(default=None, ge=0)
    reading_order: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> "SourceLocation":
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("End offset cannot be before start offset.")
        return self

    @model_validator(mode="after")
    def validate_geometry(self) -> "SourceLocation":
        coordinates = (self.x0, self.y0, self.x1, self.y1)
        if any(value is not None for value in coordinates) and any(value is None for value in coordinates):
            raise ValueError("Block geometry requires all bounding-box coordinates.")
        if self.x0 is not None and (self.x1 <= self.x0 or self.y1 <= self.y0):
            raise ValueError("Block geometry must have positive width and height.")
        return self

    @property
    def width(self) -> float | None:
        return self.x1 - self.x0 if self.x0 is not None and self.x1 is not None else None

    @property
    def height(self) -> float | None:
        return self.y1 - self.y0 if self.y0 is not None and self.y1 is not None else None

    @property
    def stable_reference(self) -> str:
        if self.page_number is None:
            return f"document:block:{self.block_index}"
        return f"page:{self.page_number}:block:{self.block_index}"

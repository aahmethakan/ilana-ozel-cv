from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.domain.career.enums import SourceType

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FactSource(BaseModel):
    """Traceable origin for a career claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: SourceType
    reference: NonEmptyText | None = None
    original_text: NonEmptyText | None = None

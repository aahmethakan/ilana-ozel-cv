from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class JobSourceType(StrEnum):
    PASTED_TEXT = "pasted_text"


class JobDocument(BaseModel):
    """Immutable, unmodified job text supplied directly by the user."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_text: str
    source_type: JobSourceType = JobSourceType.PASTED_TEXT
    title_hint: str | None = None
    company_hint: str | None = None
    source_reference: str | None = None

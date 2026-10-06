from pydantic import BaseModel, ConfigDict


class PdfExportValidationResult(BaseModel):
    """Non-sensitive structural facts about a completed PDF export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_count: int
    text: str

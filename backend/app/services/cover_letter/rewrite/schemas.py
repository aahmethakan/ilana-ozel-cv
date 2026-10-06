from pydantic import BaseModel, ConfigDict

from app.services.controlled_rewrite import FactSafetyStatus, RewriteFinalStatus, RewriteQualityStatus


class CoverLetterRewriteResult(BaseModel):
    """Public, non-evidentiary wording proposal state for one cover item."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    item_id: str
    original_text: str
    rewritten_text: str
    fact_safety: FactSafetyStatus
    quality_status: RewriteQualityStatus
    final_status: RewriteFinalStatus
    reason_code: str | None = None

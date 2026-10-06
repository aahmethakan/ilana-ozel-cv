from app.services.controlled_rewrite import (
    ControlledRewriteError,
    FactSafetyStatus,
    RewriteFinalStatus,
    RewriteQualityStatus,
    controlled_rewrite,
)
from app.services.cover_letter.rewrite.schemas import CoverLetterRewriteResult


def enhance_cover_letter_wording(*, item_id: str, original_text: str, category: str, provider=None) -> CoverLetterRewriteResult:
    """Best-effort enhancement: any failure preserves the original wording."""
    try:
        if provider is None:
            from app.ai.providers import OpenAIProvider
            provider = OpenAIProvider()
        outcome = controlled_rewrite(provider, original=original_text, mode=f"cover_letter_{category.lower()}")
        return CoverLetterRewriteResult(item_id=item_id, original_text=original_text, rewritten_text=outcome.rewritten_text, fact_safety=outcome.fact_safety_status, quality_status=outcome.quality_status, final_status=outcome.final_status)
    except ControlledRewriteError as error:
        return CoverLetterRewriteResult(item_id=item_id, original_text=original_text, rewritten_text=original_text, fact_safety=FactSafetyStatus.UNSAFE, quality_status=RewriteQualityStatus.NOT_IMPROVED, final_status=RewriteFinalStatus.REJECTED, reason_code=error.code)
    except Exception:
        return CoverLetterRewriteResult(item_id=item_id, original_text=original_text, rewritten_text=original_text, fact_safety=FactSafetyStatus.SAFE, quality_status=RewriteQualityStatus.UNCHANGED, final_status=RewriteFinalStatus.REJECTED, reason_code="provider_unavailable")

from app.services.controlled_rewrite import ControlledRewriteError, validate_rewrite
from app.services.cv_validation.schemas import ValidationIssue, ValidationSeverity
from app.services.draft_review import ReviewedCvDraft, reviewed_draft
from app.services.generation_context import GenerationContext
from app.services.generation_orchestration import GeneratedCvDraft, generate_deterministic_cv


def validate_facts(*, draft: GeneratedCvDraft, reviewed: ReviewedCvDraft, context: GenerationContext, decisions: dict, rewrites: dict) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    try:
        regenerated = generate_deterministic_cv(context, draft.plan)
        if regenerated.model_dump(mode="json") != draft.model_dump(mode="json"):
            issues.append(_block("UNSUPPORTED_CLAIM", "Bir CV maddesi doğrulanmış kaynaklarla desteklenmiyor.", "CV"))
    except Exception:
        issues.append(_block("UNSUPPORTED_CLAIM", "Bir CV maddesi doğrulanmış kaynaklarla desteklenmiyor.", "CV"))
    expected = reviewed_draft(draft, decisions, rewrites)
    if expected.model_dump(mode="json") != reviewed.model_dump(mode="json"):
        issues.append(_block("REVIEWED_CONTENT_MISMATCH", "İncelenen CV içeriği güvenilir taslakla uyumlu değil.", "CV"))
    for item in reviewed.items:
        original = next((change.original_text for change in reviewed.changes if change.item_id == item.item_id), item.text)
        if original and original != item.text:
            try:
                validate_rewrite(original=original, rewritten=item.text)
            except ControlledRewriteError:
                issues.append(_block("UNSUPPORTED_REWRITE", "Bir CV maddesi doğrulanmış kaynaklarla desteklenmiyor.", item.section.value))
    return tuple(issues)


def _block(code: str, message: str, section: str) -> ValidationIssue:
    return ValidationIssue(validator="FACT", code=code, severity=ValidationSeverity.BLOCK, message=message, section=section)

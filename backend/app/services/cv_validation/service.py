from app.services.cv_validation.ats_validator import validate_ats
from app.services.cv_validation.consistency_validator import validate_consistency
from app.services.cv_validation.fact_validator import validate_facts
from app.services.cv_validation.format_validator import validate_format
from app.services.cv_validation.language_validator import validate_language
from app.services.cv_validation.schemas import CvValidationReport, ValidationOverallStatus, ValidationSeverity, ValidatorResult
from app.services.draft_review import ReviewedCvDraft
from app.services.generation_context import GenerationContext
from app.services.generation_orchestration import GeneratedCvDraft
from app.services.public_cv_projection import PublicCvProjection


def validate_cv(*, projection: PublicCvProjection, draft: GeneratedCvDraft, context: GenerationContext, decisions: dict, rewrites: dict) -> CvValidationReport:
    """Run deterministic read-only validators in their public contract order."""
    groups = (
        ("FACT", validate_facts(draft=draft, reviewed=projection.reviewed_draft, context=context, decisions=decisions, rewrites=rewrites)),
        ("CONSISTENCY", validate_consistency(projection)),
        ("ATS", validate_ats(projection)),
        ("FORMAT", validate_format(projection)),
        ("LANGUAGE", validate_language(projection)),
    )
    issues = tuple(issue for _, values in groups for issue in values)
    def status(values):
        return ValidationSeverity.BLOCK if any(item.severity is ValidationSeverity.BLOCK for item in values) else ValidationSeverity.WARNING if any(item.severity is ValidationSeverity.WARNING for item in values) else ValidationSeverity.PASS
    validators = tuple(ValidatorResult(validator=name, status=status(values)) for name, values in groups)
    overall = ValidationOverallStatus.BLOCKED if any(item.severity is ValidationSeverity.BLOCK for item in issues) else ValidationOverallStatus.WARNING if any(item.severity is ValidationSeverity.WARNING for item in issues) else ValidationOverallStatus.PASS
    return CvValidationReport(overall_status=overall, validators=validators, issues=issues, pass_count=sum(item.status is ValidationSeverity.PASS for item in validators), warning_count=sum(item.severity is ValidationSeverity.WARNING for item in issues), block_count=sum(item.severity is ValidationSeverity.BLOCK for item in issues))

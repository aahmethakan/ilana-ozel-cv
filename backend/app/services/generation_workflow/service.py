"""Server-side composition of the existing deterministic generation services."""

from app.services.career_context import UnifiedCareerContext
from app.services.generation_context import GenerationContextNotReadyError, build_generation_context
from app.services.generation_orchestration import generate_deterministic_cv
from app.services.generation_review import GeneratedCvDraftReview, build_generated_cv_review
from app.services.generation_strategy import GenerationMode, build_generation_plan
from app.services.job_match import JobMatchResult
from app.services.profile_readiness import ReadinessStatus, assess_unified_career_readiness


class GenerationWorkflowError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def generate_review_from_context(
    *,
    context: UnifiedCareerContext,
    mode: GenerationMode,
    job_match: JobMatchResult | None = None,
) -> GeneratedCvDraftReview:
    """Derive a public review from authoritative inputs without retaining a draft."""

    readiness = assess_unified_career_readiness(context)
    if readiness.status is ReadinessStatus.BLOCKED:
        raise GenerationWorkflowError("generation_readiness_blocked", "The analyzed CV is not ready for safe generation.")
    if readiness.status is ReadinessStatus.NEEDS_REVIEW:
        raise GenerationWorkflowError("generation_readiness_needs_review", "The analyzed CV needs evidence review before generation.")
    if mode is GenerationMode.TARGETED and job_match is None:
        raise GenerationWorkflowError("targeted_job_state_missing", "Analyze a job listing for this CV before targeted generation.")
    try:
        generation_context = build_generation_context(context)
        plan = build_generation_plan(
            generation_context,
            match=job_match if mode is GenerationMode.TARGETED else None,
        )
        draft = generate_deterministic_cv(generation_context, plan)
        return build_generated_cv_review(draft)
    except GenerationContextNotReadyError as error:
        raise GenerationWorkflowError("generation_context_not_ready", "The analyzed CV is not ready for generation.") from error
    except ValueError as error:
        raise GenerationWorkflowError("generation_failed", "The CV could not be generated safely.") from error


def generate_draft_from_context(*, context: UnifiedCareerContext, mode: GenerationMode, job_match: JobMatchResult | None = None):
    """Use the same guarded pipeline but retain its immutable draft server-side."""

    readiness = assess_unified_career_readiness(context)
    if readiness.status is ReadinessStatus.BLOCKED:
        raise GenerationWorkflowError("generation_readiness_blocked", "The analyzed CV is not ready for safe generation.")
    if readiness.status is ReadinessStatus.NEEDS_REVIEW:
        raise GenerationWorkflowError("generation_readiness_needs_review", "The analyzed CV needs evidence review before generation.")
    if mode is GenerationMode.TARGETED and job_match is None:
        raise GenerationWorkflowError("targeted_job_state_missing", "Analyze a job listing for this CV before targeted generation.")
    try:
        generation_context = build_generation_context(context)
        plan = build_generation_plan(generation_context, match=job_match if mode is GenerationMode.TARGETED else None)
        return generate_deterministic_cv(generation_context, plan)
    except GenerationContextNotReadyError as error:
        raise GenerationWorkflowError("generation_context_not_ready", "The analyzed CV is not ready for generation.") from error
    except ValueError as error:
        raise GenerationWorkflowError("generation_failed", "The CV could not be generated safely.") from error

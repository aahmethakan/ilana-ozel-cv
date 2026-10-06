"""Build the immutable authoritative context retained by an analysis session."""

from collections.abc import Sequence

from app.domain.career import CareerProfile
from app.extraction.career import UnresolvedEvidence
from app.services.career_context.schemas import UnifiedCareerContext
from app.services.career_context.service import build_unified_career_context
from app.services.evidence_convergence import converge_structured_evidence
from app.services.evidence_coverage import evaluate_evidence_coverage
from app.services.structured_profile import assemble_structured_career_profile
from app.confirmation.structured.schemas import WorkExperienceResolutionResult


def build_analyzed_unified_career_context(
    *,
    profile: CareerProfile,
    unresolved_evidence: Sequence[UnresolvedEvidence] = (),
    work_results: Sequence[WorkExperienceResolutionResult] = (),
) -> UnifiedCareerContext:
    """Compose only state produced by the server-side CV analysis pipeline.

    CV extraction currently emits verified atomic facts and coarse unresolved
    evidence.  It does not fabricate structured confirmation results or
    bindings, so this composition deliberately preserves an empty structured
    resolution layer and carries unresolved evidence forward as unbound.
    Future confirmation flows can replace this aggregate with their resolved
    structured outputs through the same domain entry points.
    """

    structured_assembly = assemble_structured_career_profile(work_results=work_results)
    convergence = converge_structured_evidence(
        unresolved_evidence=unresolved_evidence,
        bindings=(),
        work_results=work_results,
        profile_result=structured_assembly,
    )
    coverage = evaluate_evidence_coverage(
        unresolved_evidence=unresolved_evidence,
        convergence_result=convergence,
        declarations=(),
    )
    return build_unified_career_context(
        atomic_profile=profile,
        structured_assembly=structured_assembly,
        evidence_convergence=convergence,
        evidence_coverage=coverage,
    )

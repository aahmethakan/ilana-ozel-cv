from app.services.career_context import build_unified_career_context
from app.services.profile_readiness import ReadinessStatus, assess_unified_career_readiness
from tests.test_career_context import atomic_ready, structured_inputs


def test_unified_readiness_is_ready_for_closed_resolved_context() -> None:
    assembly, convergence, coverage = structured_inputs()
    result = assess_unified_career_readiness(build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage))
    assert result.status is ReadinessStatus.READY


def test_unified_readiness_requires_review_for_partial_structured_record() -> None:
    assembly, convergence, coverage = structured_inputs(partial=True)
    result = assess_unified_career_readiness(build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage))
    assert result.status is ReadinessStatus.NEEDS_REVIEW
    assert [item.code for item in result.review_findings] == ["structured_record_partial", "structured_field_unresolved"]

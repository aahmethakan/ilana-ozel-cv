from app.confirmation.structured.schemas import StructuredResolutionStatus
from app.services.career_context.schemas import UnifiedCareerContext
from app.services.evidence_convergence.schemas import EvidenceConvergenceState
from app.services.evidence_coverage.schemas import EvidenceCoverageOverallState
from app.services.profile_readiness.schemas import (
    CareerProfileReadinessFinding,
    CareerProfileReadinessResult,
    ReadinessFindingImpact,
    ReadinessStatus,
)
from app.services.profile_readiness.service import assess_career_profile_readiness


def _finding(code: str, impact: ReadinessFindingImpact, message: str, *references: str) -> CareerProfileReadinessFinding:
    return CareerProfileReadinessFinding(code=code, impact=impact, message=message, source_references=tuple(reference for reference in references if reference))


def assess_unified_career_readiness(context: UnifiedCareerContext) -> CareerProfileReadinessResult:
    """Conservatively combine legacy readiness with explicit structured evidence state."""

    atomic = assess_career_profile_readiness(context.atomic_profile)
    blocking = list(atomic.blocking_findings)
    review = list(atomic.review_findings)
    assembly = context.structured_assembly

    for conflict in assembly.conflicts:
        blocking.append(_finding("structured_record_conflict", ReadinessFindingImpact.BLOCKING, "Structured record state conflicts and has no authoritative current version.", conflict.record_id))
    for entry in (*assembly.profile.work_experiences, *assembly.profile.education):
        if entry.resolution_status is StructuredResolutionStatus.PARTIALLY_RESOLVED:
            review.append(_finding("structured_record_partial", ReadinessFindingImpact.REVIEW, "A structured record remains partially resolved.", entry.record.record_id, entry.candidate_id))
    for item in context.evidence_convergence.items:
        if item.state is EvidenceConvergenceState.CONFLICT:
            blocking.append(_finding("structured_field_conflict", ReadinessFindingImpact.BLOCKING, "A bound structured field has conflicting evidence state.", item.evidence_key, item.record_id or "", item.candidate_id or "", item.field_name.value))
        elif item.state is EvidenceConvergenceState.STILL_UNRESOLVED:
            review.append(_finding("structured_field_unresolved", ReadinessFindingImpact.REVIEW, "A bound structured field remains unresolved.", item.evidence_key, item.record_id or "", item.candidate_id or "", item.field_name.value))
    unresolved_lineages = {(item.evidence_key, item.record_id, item.candidate_id) for item in context.evidence_convergence.items if item.state is EvidenceConvergenceState.STILL_UNRESOLVED}
    for item in context.evidence_coverage.items:
        if item.overall_state is EvidenceCoverageOverallState.PARTIAL:
            review.append(_finding("structured_coverage_partial", ReadinessFindingImpact.REVIEW, "Structured mapping coverage was explicitly declared partial.", item.evidence_key, item.record_id, item.candidate_id))
        elif item.overall_state is EvidenceCoverageOverallState.UNDECLARED:
            review.append(_finding("structured_coverage_undeclared", ReadinessFindingImpact.REVIEW, "Bound structured evidence has no explicit coverage declaration.", item.evidence_key, item.record_id, item.candidate_id))
        elif item.overall_state is EvidenceCoverageOverallState.COMPLETE_BUT_OPEN and (item.evidence_key, item.record_id, item.candidate_id) not in unresolved_lineages:
            review.append(_finding("structured_coverage_open", ReadinessFindingImpact.REVIEW, "Structured mapping coverage remains open.", item.evidence_key, item.record_id, item.candidate_id))
    for evidence in context.evidence_coverage.unbound_unresolved_evidence:
        review.append(_finding("unbound_unresolved_evidence", ReadinessFindingImpact.REVIEW, "Unresolved evidence has no structured binding.", evidence.block_reference))

    def canonical_findings(items: list[CareerProfileReadinessFinding], order: dict[str, int]) -> tuple[CareerProfileReadinessFinding, ...]:
        unique = {(item.code, item.source_references): item for item in items}
        return tuple(unique[key] for key in sorted(unique, key=lambda key: (order.get(key[0], 50), key)))

    blocking = list(canonical_findings(blocking, {"structured_record_conflict": 0, "structured_field_conflict": 1}))
    review = list(canonical_findings(review, {
        "structured_record_partial": 0,
        "structured_field_unresolved": 1,
        "structured_coverage_partial": 2,
        "structured_coverage_undeclared": 2,
        "structured_coverage_open": 2,
        "unbound_unresolved_evidence": 3,
    }))
    findings = tuple(blocking + review)
    status = ReadinessStatus.BLOCKED if blocking else ReadinessStatus.NEEDS_REVIEW if review else ReadinessStatus.READY
    return CareerProfileReadinessResult(
        status=status, findings=findings, blocking_findings=tuple(blocking), review_findings=tuple(review),
        trusted_summary=atomic.trusted_summary, unresolved_count=atomic.unresolved_count + len(context.evidence_coverage.unbound_unresolved_evidence), policy_version="v2",
    )

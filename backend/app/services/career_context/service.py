from app.domain.career import CareerProfile
from app.services.career_context.schemas import UnifiedCareerContext
from app.services.evidence_convergence.schemas import EvidenceConvergenceResult
from app.services.evidence_coverage.schemas import EvidenceCoverageResult
from app.services.structured_profile.schemas import StructuredCareerProfileAssemblyResult


def build_unified_career_context(*, atomic_profile: CareerProfile, structured_assembly: StructuredCareerProfileAssemblyResult, evidence_convergence: EvidenceConvergenceResult, evidence_coverage: EvidenceCoverageResult) -> UnifiedCareerContext:
    return UnifiedCareerContext(
        atomic_profile=atomic_profile,
        structured_assembly=structured_assembly,
        evidence_convergence=evidence_convergence,
        evidence_coverage=evidence_coverage,
    )

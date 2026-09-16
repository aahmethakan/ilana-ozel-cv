from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.career import CareerProfile
from app.services.evidence_convergence.schemas import EvidenceConvergenceResult
from app.services.evidence_coverage.schemas import EvidenceCoverageResult
from app.services.structured_profile.schemas import StructuredCareerProfileAssemblyResult
from app.services.evidence_convergence.schemas import EvidenceConvergenceState


class UnifiedCareerContext(BaseModel):
    """Composition only: each nested model remains the canonical owner of its own evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    atomic_profile: CareerProfile
    structured_assembly: StructuredCareerProfileAssemblyResult
    evidence_convergence: EvidenceConvergenceResult
    evidence_coverage: EvidenceCoverageResult

    @model_validator(mode="after")
    def validate_coverage_lineages_exist_in_convergence(self) -> "UnifiedCareerContext":
        for coverage in self.evidence_coverage.items:
            matching = [
                item for item in self.evidence_convergence.items
                if item.evidence_key == coverage.evidence_key
                and item.record_type is coverage.record_type
                and (
                    (item.record_id == coverage.record_id and item.candidate_id == coverage.candidate_id)
                    or (coverage.record_id in item.related_record_ids and coverage.candidate_id in item.related_candidate_ids)
                )
            ]
            matching_by_field = {item.field_name: item.state for item in matching}
            snapshot_by_field = {item.field_name: item.convergence_state for item in coverage.field_states}
            if matching_by_field != snapshot_by_field:
                raise ValueError("Coverage item lineage and fields must originate from the convergence result.")
        convergence_unbound = tuple(item.model_dump(mode="json") for item in self.evidence_convergence.unbound_unresolved_evidence)
        coverage_unbound = tuple(item.model_dump(mode="json") for item in self.evidence_coverage.unbound_unresolved_evidence)
        if convergence_unbound != coverage_unbound:
            raise ValueError("Coverage and convergence unbound evidence must match.")
        admitted = {
            (entry.record.record_id, entry.candidate_id)
            for entry in (*self.structured_assembly.profile.work_experiences, *self.structured_assembly.profile.education)
        }
        for item in self.evidence_convergence.items:
            if item.state in {EvidenceConvergenceState.RESOLVED, EvidenceConvergenceState.STILL_UNRESOLVED}:
                if item.record_id is None or item.candidate_id is None or (item.record_id, item.candidate_id) not in admitted:
                    raise ValueError("Non-conflict structured convergence must refer to an admitted structured profile lineage.")
        return self

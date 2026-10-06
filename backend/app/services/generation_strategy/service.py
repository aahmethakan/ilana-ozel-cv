"""Deterministic selection only; this service never creates or rewrites claims."""

from app.services.generation_context import GenerationContext
from app.services.job_match import JobMatchResult, RequirementMatchStatus
from app.services.generation_strategy.schemas import GenerationMode, GenerationPlan, GenerationSelection, GenerationTargetSection


def build_generation_plan(context: GenerationContext, match: JobMatchResult | None = None) -> GenerationPlan:
    """Select exact eligible evidence once; role targeting requires exact association lineage."""
    selections: list[GenerationSelection] = []
    requirements = () if match is None else tuple(sorted(match.requirement_results, key=lambda item: item.requirement.requirement_id))
    for result in requirements:
        if result.status not in {RequirementMatchStatus.MATCHED, RequirementMatchStatus.PARTIAL}:
            continue
        target = result.requirement.text.strip().casefold()
        for atomic in sorted(context.atomic_claims, key=lambda item: item.evidence_id):
            if atomic.statement.strip().casefold() != target:
                continue
            associations = tuple(sorted((item for item in context.work_fact_associations if item.atomic_evidence_id == atomic.evidence_id), key=lambda item: item.association_evidence_id))
            if associations:
                for association in associations:
                    selections.append(GenerationSelection(requirement_id=result.requirement.requirement_id, atomic_evidence_id=atomic.evidence_id, target_section=GenerationTargetSection.WORK_EXPERIENCE, selection_reason="direct_requirement_support", association_evidence_id=association.association_evidence_id, work_record_id=association.work_record_id, work_candidate_id=association.work_candidate_id))
            else:
                selections.append(GenerationSelection(requirement_id=result.requirement.requirement_id, atomic_evidence_id=atomic.evidence_id, target_section=GenerationTargetSection.SKILLS, selection_reason="direct_requirement_support"))
    if match is None:
        for atomic in sorted(context.atomic_claims, key=lambda item: item.evidence_id):
            associations = tuple(sorted(
                (item for item in context.work_fact_associations if item.atomic_evidence_id == atomic.evidence_id),
                key=lambda item: item.association_evidence_id,
            ))
            if associations:
                for association in associations:
                    selections.append(GenerationSelection(
                        atomic_evidence_id=atomic.evidence_id,
                        target_section=GenerationTargetSection.WORK_EXPERIENCE,
                        selection_reason="general_associated_work_evidence",
                        association_evidence_id=association.association_evidence_id,
                        work_record_id=association.work_record_id,
                        work_candidate_id=association.work_candidate_id,
                    ))
            else:
                selections.append(GenerationSelection(
                    atomic_evidence_id=atomic.evidence_id,
                    target_section=GenerationTargetSection.SKILLS,
                    selection_reason="general_eligible_evidence",
                ))
    unique = {selection.model_dump_json(): selection for selection in selections}
    return GenerationPlan(mode=GenerationMode.TARGETED if match is not None else GenerationMode.GENERAL, selections=tuple(sorted(unique.values(), key=lambda item: (item.requirement_id or "", item.atomic_evidence_id, item.work_record_id or "", item.work_candidate_id or ""))))

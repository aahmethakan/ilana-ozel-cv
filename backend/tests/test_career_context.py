import pytest
from pydantic import ValidationError

from app.confirmation.structured import (
    StructuredFieldAction, StructuredRecordOrigin, TextFieldDecision, WorkExperienceFieldDecisions,
    create_work_experience_candidate, resolve_work_experience_candidate,
)
from app.domain.career import CareerFact, CareerProfile, ContactInfo, ContactValue, FactSource, ProvenancedText, SourceType, VerificationStatus
from app.domain.document import SectionType
from app.extraction.career import UnresolvedEvidence
from app.services.career_context import UnifiedCareerContext, build_unified_career_context
from app.services.evidence_convergence import WorkEvidenceResolutionBinding, WorkExperienceField, converge_structured_evidence, unresolved_evidence_key
from app.services.evidence_coverage import EvidenceCoverageStatus, WorkEvidenceCoverageDeclaration, evaluate_evidence_coverage
from app.services.structured_profile import assemble_structured_career_profile


def source(reference: str) -> FactSource:
    return FactSource(source_type=SourceType.MASTER_CV, reference=reference, original_text="Synthetic context evidence")


def atomic_ready() -> CareerProfile:
    return CareerProfile(
        contact=ContactInfo(email=ContactValue(value="person@example.test", source=source("page:1:contact"))),
        skills=(CareerFact(statement="Python", verification_status=VerificationStatus.VERIFIED, source=source("page:1:skill")),),
    )


def structured_inputs(*, partial: bool = False):
    evidence = UnresolvedEvidence(block_reference="page:1:block:1", section_type=SectionType.EXPERIENCE, reason="ambiguous")
    inferred = lambda value: ProvenancedText(value=value, verification_status=VerificationStatus.INFERRED_UNVERIFIED, value_source=source(evidence.block_reference), evidence_sources=(source(evidence.block_reference),))
    candidate = create_work_experience_candidate(origin=StructuredRecordOrigin(evidence_sources=(source(evidence.block_reference),)), company=inferred("ACME"), title=inferred("Engineer"))
    result = resolve_work_experience_candidate(candidate, WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        title=TextFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED if partial else StructuredFieldAction.ACCEPT),
    ), user_input_reference="review:context")
    bindings = tuple(WorkEvidenceResolutionBinding(evidence_key=unresolved_evidence_key(evidence), record_id=candidate.record_id, candidate_id=candidate.candidate_id, field_name=field) for field in (WorkExperienceField.COMPANY, WorkExperienceField.TITLE))
    assembly = assemble_structured_career_profile(work_results=(result,))
    convergence = converge_structured_evidence(unresolved_evidence=(evidence,), bindings=bindings, work_results=(result,), profile_result=assembly)
    coverage = evaluate_evidence_coverage(
        unresolved_evidence=(evidence,), convergence_result=convergence,
        declarations=(WorkEvidenceCoverageDeclaration(evidence_key=unresolved_evidence_key(evidence), record_id=candidate.record_id, candidate_id=candidate.candidate_id, covered_fields=(WorkExperienceField.COMPANY, WorkExperienceField.TITLE), coverage_status=EvidenceCoverageStatus.DECLARED_COMPLETE),),
    )
    return assembly, convergence, coverage


def test_context_preserves_components_and_rejects_unrelated_coverage() -> None:
    assembly, convergence, coverage = structured_inputs()
    context = build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    assert context.structured_assembly is assembly
    assert UnifiedCareerContext.model_validate(context.model_dump(mode="json")) == context
    with pytest.raises(ValidationError):
        context.atomic_profile = CareerProfile()
    bad = coverage.model_copy(update={"items": (coverage.items[0].model_copy(update={"candidate_id": "wrong"}),)})
    with pytest.raises(ValidationError):
        build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=bad)

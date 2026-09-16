import pytest
from pydantic import ValidationError

from app.confirmation.structured import (
    StructuredFieldAction,
    StructuredRecordOrigin,
    TextFieldDecision,
    WorkExperienceFieldDecisions,
    create_work_experience_candidate,
    resolve_work_experience_candidate,
)
from app.domain.career import FactSource, ProvenancedText, SourceType, VerificationStatus
from app.domain.document import SectionType
from app.extraction.career import UnresolvedEvidence
from app.services.evidence_convergence import (
    EvidenceConvergenceState,
    WorkEvidenceResolutionBinding,
    WorkExperienceField,
    converge_structured_evidence,
    unresolved_evidence_key,
)
from app.services.evidence_coverage import (
    EvidenceCoverageOverallState,
    EvidenceCoverageFieldState,
    EvidenceCoverageItem,
    EvidenceCoverageResult,
    EvidenceCoverageStatus,
    WorkEvidenceCoverageDeclaration,
    coverage_id,
    evaluate_evidence_coverage,
)
from app.services.structured_profile import assemble_structured_career_profile


def source(reference: str) -> FactSource:
    return FactSource(source_type=SourceType.MASTER_CV, reference=reference, original_text="Synthetic coverage evidence")


def value(text: str, reference: str) -> ProvenancedText:
    return ProvenancedText(value=text, verification_status=VerificationStatus.INFERRED_UNVERIFIED, value_source=source(reference), evidence_sources=(source(reference),))


def fixture(*, reject_title: bool = False, leave_title: bool = False):
    evidence = UnresolvedEvidence(block_reference="page:1:block:1", section_type=SectionType.EXPERIENCE, reason="ambiguous_experience_content")
    candidate = create_work_experience_candidate(
        origin=StructuredRecordOrigin(evidence_sources=(source(evidence.block_reference),)),
        company=value("ACME", evidence.block_reference), title=value("Engineer", evidence.block_reference),
    )
    result = resolve_work_experience_candidate(candidate, WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        title=TextFieldDecision(action=StructuredFieldAction.REJECT if reject_title else StructuredFieldAction.LEAVE_UNRESOLVED if leave_title else StructuredFieldAction.ACCEPT),
    ), user_input_reference="review:coverage")
    bindings = tuple(
        WorkEvidenceResolutionBinding(evidence_key=unresolved_evidence_key(evidence), record_id=candidate.record_id, candidate_id=candidate.candidate_id, field_name=field)
        for field in (WorkExperienceField.COMPANY, WorkExperienceField.TITLE)
    )
    profile = assemble_structured_career_profile(work_results=(result,))
    convergence = converge_structured_evidence(unresolved_evidence=(evidence,), bindings=bindings, work_results=(result,), profile_result=profile)
    return evidence, result, convergence


def declaration(evidence, result, fields, status=EvidenceCoverageStatus.DECLARED_COMPLETE):
    return WorkEvidenceCoverageDeclaration(
        evidence_key=unresolved_evidence_key(evidence), record_id=result.candidate.record_id,
        candidate_id=result.candidate.candidate_id, covered_fields=fields, coverage_status=status,
    )


def test_complete_closed_open_partial_and_rejected_are_distinguished() -> None:
    evidence, result, convergence = fixture()
    closed = evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=(declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.TITLE)),))
    assert closed.items[0].overall_state is EvidenceCoverageOverallState.COMPLETE_AND_CLOSED

    evidence, result, convergence = fixture(leave_title=True)
    open_result = evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=(declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.TITLE)),))
    assert open_result.items[0].overall_state is EvidenceCoverageOverallState.COMPLETE_BUT_OPEN

    evidence, result, convergence = fixture(reject_title=True)
    rejected = evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=(declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.TITLE)),))
    assert rejected.items[0].overall_state is EvidenceCoverageOverallState.COMPLETE_AND_CLOSED
    assert rejected.items[0].field_states[1].convergence_state is EvidenceConvergenceState.REJECTED

    partial = evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=(declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.TITLE), EvidenceCoverageStatus.DECLARED_PARTIAL),))
    assert partial.items[0].overall_state is EvidenceCoverageOverallState.PARTIAL


def test_undeclared_and_unbound_evidence_remain_explicitly_open() -> None:
    evidence, result, convergence = fixture()
    undeclared = evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=())
    assert undeclared.items[0].overall_state is EvidenceCoverageOverallState.UNDECLARED
    other = UnresolvedEvidence(block_reference="page:1:block:2", section_type=SectionType.EXPERIENCE, reason="other")
    output = evaluate_evidence_coverage(unresolved_evidence=(evidence, other), convergence_result=convergence, declarations=())
    assert output.unbound_unresolved_evidence == (other,)


def test_declarations_require_exact_fields_lineage_and_nonempty_unique_fields() -> None:
    evidence, result, convergence = fixture()
    with pytest.raises(ValueError, match="exactly match"):
        evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=(declaration(evidence, result, (WorkExperienceField.COMPANY,)),))
    wrong = declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.TITLE)).model_copy(update={"candidate_id": "wrong"})
    with pytest.raises(ValueError, match="exactly match"):
        evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=(wrong,))
    with pytest.raises(ValidationError):
        declaration(evidence, result, ())
    with pytest.raises(ValidationError):
        declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.COMPANY))


def test_duplicate_conflicting_and_reordered_declarations_are_deterministic() -> None:
    evidence, result, convergence = fixture()
    forward = declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.TITLE))
    reverse = declaration(evidence, result, (WorkExperienceField.TITLE, WorkExperienceField.COMPANY))
    assert coverage_id(forward) == coverage_id(reverse)
    output = evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=(forward, forward))
    assert len(output.items) == 1
    assert [field.value for field in output.items[0].covered_fields] == ["company", "title"]
    partial = declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.TITLE), EvidenceCoverageStatus.DECLARED_PARTIAL)
    with pytest.raises(ValueError, match="Conflicting"):
        evaluate_evidence_coverage(unresolved_evidence=(evidence,), convergence_result=convergence, declarations=(forward, partial))


def test_coverage_items_validate_ids_states_immutability_and_serialization() -> None:
    evidence, result, convergence = fixture()
    output = evaluate_evidence_coverage(
        unresolved_evidence=(evidence,), convergence_result=convergence,
        declarations=(declaration(evidence, result, (WorkExperienceField.COMPANY, WorkExperienceField.TITLE)),),
    )
    item = output.items[0]
    assert EvidenceCoverageResult.model_validate(output.model_dump(mode="json")) == output
    with pytest.raises(ValidationError):
        item.overall_state = EvidenceCoverageOverallState.PARTIAL
    with pytest.raises(ValidationError):
        EvidenceCoverageItem(
            coverage_id="coverage:spoofed", evidence_key=item.evidence_key, record_type=item.record_type,
            record_id=item.record_id, candidate_id=item.candidate_id, covered_fields=item.covered_fields,
            coverage_status=item.coverage_status, field_states=item.field_states,
            overall_state=item.overall_state,
        )
    with pytest.raises(ValidationError):
        EvidenceCoverageItem(
            coverage_id=item.coverage_id, evidence_key=item.evidence_key, record_type=item.record_type,
            record_id=item.record_id, candidate_id=item.candidate_id, covered_fields=item.covered_fields,
            coverage_status=EvidenceCoverageStatus.DECLARED_PARTIAL, field_states=item.field_states,
            overall_state=EvidenceCoverageOverallState.COMPLETE_AND_CLOSED,
        )

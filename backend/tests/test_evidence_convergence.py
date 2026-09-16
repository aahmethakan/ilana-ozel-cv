import pytest
from pydantic import ValidationError

from app.confirmation.structured import (
    CareerDateFieldDecision,
    EducationFieldDecisions,
    StructuredFieldAction,
    StructuredRecordOrigin,
    TextFieldDecision,
    WholeRecordAction,
    WorkExperienceFieldDecisions,
    create_education_candidate,
    create_work_experience_candidate,
    resolve_education_candidate,
    resolve_work_experience_candidate,
)
from app.domain.career import CareerDate, FactSource, ProvenancedCareerDate, ProvenancedText, SourceType, VerificationStatus
from app.domain.document import SectionType
from app.extraction.career import UnresolvedEvidence
from app.services.evidence_convergence import (
    EducationEvidenceResolutionBinding,
    EducationField,
    EvidenceConvergenceBasis,
    EvidenceConvergenceItem,
    EvidenceConvergenceResult,
    EvidenceConvergenceState,
    WorkEvidenceResolutionBinding,
    WorkExperienceField,
    converge_structured_evidence,
    unresolved_evidence_key,
)
from app.services.structured_profile import assemble_structured_career_profile


def source(reference: str) -> FactSource:
    return FactSource(source_type=SourceType.MASTER_CV, reference=reference, original_text="Synthetic structured evidence")


def text(value: str, reference: str, status: VerificationStatus = VerificationStatus.INFERRED_UNVERIFIED) -> ProvenancedText:
    return ProvenancedText(value=value, verification_status=status, value_source=source(reference), evidence_sources=(source(reference),))


def date(year: int, reference: str) -> ProvenancedCareerDate:
    return ProvenancedCareerDate(value=CareerDate(year=year), verification_status=VerificationStatus.INFERRED_UNVERIFIED, value_source=source(reference), evidence_sources=(source(reference),))


def unresolved(reference: str = "page:1:block:1") -> UnresolvedEvidence:
    return UnresolvedEvidence(block_reference=reference, section_type=SectionType.EXPERIENCE, reason="ambiguous_structured_record")


def work_resolution(*, verified_company: bool = False, title: str = "Engineer", decisions: WorkExperienceFieldDecisions | None = None, whole_reject: bool = False):
    evidence = unresolved()
    candidate = create_work_experience_candidate(
        origin=StructuredRecordOrigin(evidence_sources=(source(evidence.block_reference),)),
        company=text("ACME", evidence.block_reference, VerificationStatus.VERIFIED if verified_company else VerificationStatus.INFERRED_UNVERIFIED),
        title=text(title, evidence.block_reference),
        start_date=date(2021, evidence.block_reference),
    )
    result = resolve_work_experience_candidate(
        candidate,
        decisions or WorkExperienceFieldDecisions(company=TextFieldDecision(action=StructuredFieldAction.ACCEPT), title=TextFieldDecision(action=StructuredFieldAction.ACCEPT)),
        user_input_reference="review:synthetic",
        whole_record_action=WholeRecordAction.REJECT_RECORD if whole_reject else None,
    )
    return evidence, result


def binding(evidence: UnresolvedEvidence, result, field: WorkExperienceField) -> WorkEvidenceResolutionBinding:
    return WorkEvidenceResolutionBinding(
        evidence_key=unresolved_evidence_key(evidence),
        record_id=result.candidate.record_id,
        candidate_id=result.candidate.candidate_id,
        field_name=field,
    )


def converge(evidence, results, bindings):
    profile = assemble_structured_career_profile(work_results=results)
    return converge_structured_evidence(unresolved_evidence=(evidence,), bindings=bindings, work_results=results, profile_result=profile)


def test_explicit_field_bindings_converge_independently_without_closing_a_block() -> None:
    evidence, result = work_resolution(decisions=WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        start_date=CareerDateFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED),
    ))
    output = converge(evidence, (result,), (
        binding(evidence, result, WorkExperienceField.COMPANY),
        binding(evidence, result, WorkExperienceField.TITLE),
        binding(evidence, result, WorkExperienceField.START_DATE),
    ))

    assert [(item.field_name.value, item.state, item.basis) for item in output.items] == [
        ("company", EvidenceConvergenceState.RESOLVED, EvidenceConvergenceBasis.USER_CONFIRMED),
        ("title", EvidenceConvergenceState.RESOLVED, EvidenceConvergenceBasis.USER_CONFIRMED),
        ("start_date", EvidenceConvergenceState.STILL_UNRESOLVED, EvidenceConvergenceBasis.UNRESOLVED),
    ]
    assert output.unbound_unresolved_evidence == ()


def test_correct_verified_leave_and_user_provided_leave_have_distinct_safe_bases() -> None:
    evidence, corrected = work_resolution(title="Senior Engineer", decisions=WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        title=TextFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value="Engineer"),
    ))
    corrected_output = converge(evidence, (corrected,), (binding(evidence, corrected, WorkExperienceField.TITLE),))
    assert corrected_output.items[0].state is EvidenceConvergenceState.RESOLVED
    assert corrected_output.items[0].basis is EvidenceConvergenceBasis.USER_CORRECTED

    verified_evidence, verified = work_resolution(verified_company=True, decisions=WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED),
        title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
    ))
    verified_output = converge(verified_evidence, (verified,), (binding(verified_evidence, verified, WorkExperienceField.COMPANY),))
    assert verified_output.items[0].basis is EvidenceConvergenceBasis.PREEXISTING_VERIFIED

    user_company = verified.resolved_record.company.model_copy(update={"verification_status": VerificationStatus.USER_PROVIDED})
    user_audit = verified.audit.model_copy(update={
        "field_audits": tuple(
            item.model_copy(update={"resolved_value": user_company}) if item.field_name == "company" else item
            for item in verified.audit.field_audits
        )
    })
    user_value = verified.model_copy(update={
        "resolved_record": verified.resolved_record.model_copy(update={"company": user_company}),
        "audit": user_audit,
    })
    user_output = converge(verified_evidence, (user_value,), (binding(verified_evidence, user_value, WorkExperienceField.COMPANY),))
    assert user_output.items[0].basis is EvidenceConvergenceBasis.PREEXISTING_USER_PROVIDED


def test_rejection_invalid_and_profile_conflicts_never_close_evidence() -> None:
    evidence, rejected = work_resolution(whole_reject=True)
    rejected_output = converge(evidence, (rejected,), (binding(evidence, rejected, WorkExperienceField.COMPANY),))
    assert rejected_output.items[0].state is EvidenceConvergenceState.REJECTED

    evidence, invalid = work_resolution(decisions=WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        start_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2024)),
        end_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2021)),
    ))
    invalid_output = converge(evidence, (invalid,), (binding(evidence, invalid, WorkExperienceField.COMPANY),))
    assert invalid_output.items[0].state is EvidenceConvergenceState.CONFLICT
    assert invalid_output.items[0].issue_codes == ("invalid_structured_resolution",)

    evidence, accepted = work_resolution()
    _, conflict = work_resolution(title="Senior Engineer")
    conflict_output = converge(evidence, (accepted, conflict), (binding(evidence, accepted, WorkExperienceField.COMPANY),))
    assert conflict_output.items[0].state is EvidenceConvergenceState.CONFLICT
    assert conflict_output.items[0].issue_codes == ("profile_record_conflict",)


def test_field_rejection_and_same_state_lineage_profile_conflict_are_distinct() -> None:
    evidence, field_rejected = work_resolution(decisions=WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.REJECT),
        title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
    ))
    rejected_output = converge(evidence, (field_rejected,), (binding(evidence, field_rejected, WorkExperienceField.COMPANY),))
    assert rejected_output.items[0].state is EvidenceConvergenceState.REJECTED
    assert rejected_output.items[0].basis is EvidenceConvergenceBasis.USER_REJECTED

    evidence, first = work_resolution()
    alternate_candidate = create_work_experience_candidate(
        origin=first.candidate.origin,
        company=first.candidate.company,
        title=first.candidate.title,
        location=text("Istanbul", evidence.block_reference),
        start_date=first.candidate.start_date,
    )
    alternate = resolve_work_experience_candidate(
        alternate_candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            location=TextFieldDecision(action=StructuredFieldAction.REJECT),
        ),
        user_input_reference="review:synthetic",
    )
    output = converge(evidence, (first, alternate), (binding(evidence, first, WorkExperienceField.COMPANY),))
    assert output.items[0].state is EvidenceConvergenceState.CONFLICT
    assert output.items[0].issue_codes == ("profile_record_conflict",)


def test_exact_duplicate_binding_deduplicates_but_different_lineage_conflicts() -> None:
    evidence, result = work_resolution()
    exact = binding(evidence, result, WorkExperienceField.COMPANY)
    output = converge(evidence, (result,), (exact, exact))
    assert len(output.items) == 1

    alternate_candidate = create_work_experience_candidate(
        origin=result.candidate.origin,
        company=result.candidate.company,
        title=result.candidate.title,
        location=text("Istanbul", evidence.block_reference),
        start_date=result.candidate.start_date,
    )
    alternate = resolve_work_experience_candidate(
        alternate_candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            location=TextFieldDecision(action=StructuredFieldAction.REJECT),
        ),
        user_input_reference="review:synthetic",
    )
    conflict_binding = binding(evidence, alternate, WorkExperienceField.COMPANY)
    output = converge(evidence, (result, alternate), (exact, conflict_binding))
    assert output.items[0].state is EvidenceConvergenceState.CONFLICT
    assert output.items[0].issue_codes == ("conflicting_evidence_field_bindings",)
    reverse = converge(evidence, (result, alternate), (conflict_binding, exact))
    assert reverse.items[0].model_dump() == output.items[0].model_dump()


def test_unbound_evidence_is_preserved_and_invalid_bindings_are_rejected() -> None:
    evidence, result = work_resolution()
    other = unresolved("page:1:block:2")
    output = converge_structured_evidence(
        unresolved_evidence=(evidence, other),
        bindings=(binding(evidence, result, WorkExperienceField.COMPANY),),
        work_results=(result,),
        profile_result=assemble_structured_career_profile(work_results=(result,)),
    )
    assert output.unbound_unresolved_evidence == (other,)
    bad = binding(evidence, result, WorkExperienceField.COMPANY).model_copy(update={"candidate_id": "wrong"})
    with pytest.raises(ValueError, match="does not match a supplied"):
        converge(evidence, (result,), (bad,))
    wrong_record = binding(evidence, result, WorkExperienceField.COMPANY).model_copy(update={"record_id": "wrong"})
    with pytest.raises(ValueError, match="does not match a supplied"):
        converge(evidence, (result,), (wrong_record,))


def test_education_typing_serialization_immutability_and_no_automatic_matching() -> None:
    evidence = UnresolvedEvidence(block_reference="page:1:education:1", section_type=SectionType.EDUCATION, reason="ambiguous_degree")
    candidate = create_education_candidate(
        origin=StructuredRecordOrigin(evidence_sources=(source(evidence.block_reference),)),
        institution=text("Y University", evidence.block_reference),
        degree=text("BSc", evidence.block_reference),
    )
    result = resolve_education_candidate(candidate, EducationFieldDecisions(
        institution=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        degree=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
    ), user_input_reference="review:education")
    profile = assemble_structured_career_profile(education_results=(result,))
    entry = EducationEvidenceResolutionBinding(
        evidence_key=unresolved_evidence_key(evidence), record_id=result.candidate.record_id,
        candidate_id=result.candidate.candidate_id, field_name=EducationField.DEGREE,
    )
    output = converge_structured_evidence(unresolved_evidence=(evidence,), bindings=(entry,), education_results=(result,), profile_result=profile)
    assert output.items[0].state is EvidenceConvergenceState.RESOLVED
    assert EvidenceConvergenceResult.model_validate(output.model_dump(mode="json")) == output
    with pytest.raises(ValidationError):
        entry.field_name = EducationField.INSTITUTION
    with pytest.raises(ValidationError):
        WorkEvidenceResolutionBinding(
            evidence_key=unresolved_evidence_key(evidence), record_id=result.candidate.record_id,
            candidate_id=result.candidate.candidate_id, field_name="degree",
        )


def test_evidence_keys_are_deterministic_and_item_state_basis_is_constrained() -> None:
    evidence = unresolved()
    same = unresolved()
    different_diagnostic = UnresolvedEvidence(
        block_reference=evidence.block_reference,
        section_type=evidence.section_type,
        reason="different_diagnostic_reason",
    )
    assert unresolved_evidence_key(evidence) == unresolved_evidence_key(same)
    assert unresolved_evidence_key(evidence) != unresolved_evidence_key(different_diagnostic)
    with pytest.raises(ValidationError):
        EvidenceConvergenceItem(
            evidence_key=unresolved_evidence_key(evidence),
            field_name=WorkExperienceField.COMPANY,
            state=EvidenceConvergenceState.RESOLVED,
            basis=EvidenceConvergenceBasis.USER_REJECTED,
        )

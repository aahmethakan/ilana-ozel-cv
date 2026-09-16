import inspect

import pytest
from pydantic import ValidationError

from app.confirmation.career import ConfirmationAction, resolve_candidate
from app.confirmation.structured import (
    BoolFieldDecision,
    CareerDateFieldDecision,
    EducationFieldDecisions,
    StructuredFieldAction,
    StructuredRecordOrigin,
    StructuredResolutionStatus,
    TextFieldDecision,
    WholeRecordAction,
    WorkExperienceFieldDecisions,
    create_education_candidate,
    create_work_experience_candidate,
    resolve_education_candidate,
    resolve_work_experience_candidate,
)
from app.confirmation.structured import service as structured_service
from app.domain.career import CareerDate, CareerProfile, FactSource, ProvenancedBool, ProvenancedCareerDate, ProvenancedText, SourceType, VerificationStatus
from app.domain.career.profile import Education, WorkExperience
from app.services.career_profile_assembly import assemble_verified_career_profile
from app.services.profile_readiness import assess_career_profile_readiness


def source(source_type: SourceType = SourceType.MASTER_CV, reference: str = "page:1:block:1") -> FactSource:
    return FactSource(source_type=source_type, reference=reference, original_text="Synthetic source evidence")


def text(value: str, status: VerificationStatus = VerificationStatus.INFERRED_UNVERIFIED, reference: str = "page:1:block:1") -> ProvenancedText:
    return ProvenancedText(value=value, verification_status=status, value_source=source(SourceType.MASTER_CV, reference), evidence_sources=(source(SourceType.MASTER_CV, reference),))


def date(year: int, month: int | None = None, status: VerificationStatus = VerificationStatus.INFERRED_UNVERIFIED, reference: str = "page:1:block:2") -> ProvenancedCareerDate:
    return ProvenancedCareerDate(value=CareerDate(year=year, month=month), verification_status=status, value_source=source(SourceType.MASTER_CV, reference), evidence_sources=(source(SourceType.MASTER_CV, reference),))


def boolean(value: bool, status: VerificationStatus = VerificationStatus.INFERRED_UNVERIFIED) -> ProvenancedBool:
    return ProvenancedBool(value=value, verification_status=status, value_source=source(SourceType.MASTER_CV), evidence_sources=(source(SourceType.MASTER_CV),))


def origin(reference: str = "page:1:experience-group:1") -> StructuredRecordOrigin:
    return StructuredRecordOrigin(evidence_sources=(source(SourceType.MASTER_CV, reference),))


def work_candidate(reference: str = "page:1:experience-group:1"):
    return create_work_experience_candidate(
        origin=origin(reference), company=text("ACME", reference=reference), title=text("Senior Engineer", reference=reference), start_date=date(2021, reference=reference), end_date=date(2024, reference=reference)
    )


def test_ids_are_deterministic_origin_based_and_proposal_sensitive() -> None:
    first = work_candidate()
    same_record_changed_title = create_work_experience_candidate(origin=origin(), company=text("ACME"), title=text("Engineer"))
    different_origin = work_candidate("page:1:experience-group:2")
    education_a = create_education_candidate(origin=origin("page:1:education-group:1"), institution=text("Example University"))
    education_b = create_education_candidate(origin=origin("page:1:education-group:2"), institution=text("Example University"))

    assert first.record_id == same_record_changed_title.record_id
    assert first.candidate_id != same_record_changed_title.candidate_id
    assert first.record_id != different_origin.record_id
    assert education_a.record_id != education_b.record_id
    assert work_candidate() == first


def test_record_identity_canonicalizes_evidence_order_and_duplicates_but_keeps_audit_sources() -> None:
    first_source = source(SourceType.MASTER_CV, "page:1:block:1")
    second_source = source(SourceType.MASTER_CV, "page:1:block:2")
    ordered = StructuredRecordOrigin(evidence_sources=(first_source, second_source))
    reordered_with_duplicate = StructuredRecordOrigin(evidence_sources=(second_source, first_source, first_source))
    first = create_work_experience_candidate(origin=ordered, company=text("ACME"))
    second = create_work_experience_candidate(origin=reordered_with_duplicate, company=text("ACME"))
    work = create_work_experience_candidate(origin=StructuredRecordOrigin(origin_reference="shared-origin"), company=text("ACME"))
    education = create_education_candidate(origin=StructuredRecordOrigin(origin_reference="shared-origin"), institution=text("Example University"))

    assert first.record_id == second.record_id
    assert reordered_with_duplicate.evidence_sources == (second_source, first_source, first_source)
    assert work.record_id != education.record_id


def test_candidate_id_changes_when_only_field_provenance_changes() -> None:
    first = create_work_experience_candidate(origin=origin(), company=text("ACME", reference="page:1:block:1"))
    changed_provenance = create_work_experience_candidate(origin=origin(), company=text("ACME", reference="page:1:block:2"))

    assert first.record_id == changed_provenance.record_id
    assert first.candidate_id != changed_provenance.candidate_id


def test_user_created_origin_requires_a_stable_explicit_reference() -> None:
    with pytest.raises(ValidationError):
        StructuredRecordOrigin()

    candidate = create_work_experience_candidate(
        origin=StructuredRecordOrigin(origin_reference="profile-form:employment:1"),
        company=ProvenancedText(value="ACME", verification_status=VerificationStatus.USER_PROVIDED, value_source=source(SourceType.USER_INPUT, "profile-form:employment:1")),
    )
    assert candidate.origin.evidence_sources == ()


def test_work_field_actions_are_independent_and_preserve_original_evidence() -> None:
    candidate = work_candidate()
    result = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            title=TextFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value="Engineer"),
            start_date=CareerDateFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED),
            end_date=CareerDateFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED),
        ),
        user_input_reference="structured-review:work:1",
    )

    assert result.status is StructuredResolutionStatus.RESOLVED
    assert result.resolved_record is not None
    assert result.resolved_record.company is not None and result.resolved_record.company.verification_status is VerificationStatus.USER_PROVIDED
    assert result.resolved_record.title is not None and result.resolved_record.title.value == "Engineer"
    assert result.resolved_record.title.value_source.source_type is SourceType.USER_INPUT
    assert result.resolved_record.title.evidence_sources == candidate.title.evidence_sources
    assert result.resolved_record.start_date is not None and result.resolved_record.start_date.is_claim_usable is False
    assert result.audit.field_audits[1].original_proposed_value is not None
    assert result.audit.field_audits[1].original_proposed_value.value == "Senior Engineer"


def test_leave_verified_preserves_trust_while_leave_inferred_does_not() -> None:
    candidate = create_work_experience_candidate(
        origin=origin(), company=text("ACME", VerificationStatus.VERIFIED), title=text("Senior Engineer"),
    )
    result = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED),
            title=TextFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED),
        ),
    )

    assert result.status is StructuredResolutionStatus.PARTIALLY_RESOLVED
    assert result.resolved_record is not None
    assert result.resolved_record.company is not None and result.resolved_record.company.is_claim_usable
    assert result.resolved_record.title is not None and result.resolved_record.title.is_claim_usable is False


@pytest.mark.parametrize("action", (StructuredFieldAction.ACCEPT, StructuredFieldAction.REJECT, StructuredFieldAction.LEAVE_UNRESOLVED))
def test_missing_field_non_correction_decisions_are_invalid(action: StructuredFieldAction) -> None:
    candidate = create_work_experience_candidate(origin=origin(), company=text("ACME"), title=text("Engineer"))
    result = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(end_date=CareerDateFieldDecision(action=action)),
        user_input_reference="structured-review:work:2",
    )

    assert result.status is StructuredResolutionStatus.INVALID
    assert result.issue_codes == ("decision_for_missing_end_date",)


def test_missing_field_correction_and_rejected_field_follow_policy() -> None:
    candidate = create_work_experience_candidate(origin=origin(), company=text("ACME"), title=text("Engineer"))
    added = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            end_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2024, month=6)),
        ),
        user_input_reference="structured-review:work:2",
    )
    rejected = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            title=TextFieldDecision(action=StructuredFieldAction.REJECT),
        ),
        user_input_reference="structured-review:work:2",
    )

    assert added.resolved_record is not None and added.resolved_record.end_date is not None
    assert added.resolved_record.end_date.verification_status is VerificationStatus.USER_PROVIDED
    assert rejected.resolved_record is not None and rejected.resolved_record.title is None
    assert rejected.audit.field_audits[1].action is StructuredFieldAction.REJECT
    assert rejected.audit.field_audits[1].original_proposed_value == candidate.title


def test_correction_payloads_are_strictly_typed_and_invalid_is_atomic() -> None:
    candidate = work_candidate()
    with pytest.raises(ValidationError):
        CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value="2024")
    with pytest.raises(ValidationError):
        BoolFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value="yes")
    with pytest.raises(ValidationError):
        TextFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2024))

    invalid = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            start_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2025)),
            end_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2024)),
        ),
        user_input_reference="structured-review:work:atomic",
    )

    assert invalid.status is StructuredResolutionStatus.INVALID
    assert invalid.resolved_record is None


def test_work_date_and_current_conflicts_are_safe_but_indeterminate_precision_is_allowed() -> None:
    candidate = work_candidate()
    current_conflict = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            is_current=BoolFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=True),
            end_date=CareerDateFieldDecision(action=StructuredFieldAction.ACCEPT),
        ),
        user_input_reference="structured-review:work:3",
    )
    inverted = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            start_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2025)),
            end_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2024)),
        ),
        user_input_reference="structured-review:work:4",
    )
    indeterminate = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            start_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2024)),
            end_date=CareerDateFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=CareerDate(year=2024, month=5)),
        ),
        user_input_reference="structured-review:work:5",
    )

    assert current_conflict.issue_codes == ("current_role_has_usable_end_date",)
    assert inverted.issue_codes == ("start_date_definitely_after_end_date",)
    assert indeterminate.status is StructuredResolutionStatus.PARTIALLY_RESOLVED
    assert indeterminate.resolved_record is not None and indeterminate.resolved_record.is_current is None


def test_missing_end_date_does_not_imply_current_and_whole_record_rejection_preserves_audit() -> None:
    candidate = create_work_experience_candidate(origin=origin(), company=text("ACME"), title=text("Engineer"))
    resolved = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(company=TextFieldDecision(action=StructuredFieldAction.ACCEPT), title=TextFieldDecision(action=StructuredFieldAction.ACCEPT)),
        user_input_reference="structured-review:work:6",
    )
    rejected = resolve_work_experience_candidate(candidate, WorkExperienceFieldDecisions(), whole_record_action=WholeRecordAction.REJECT_RECORD)

    assert resolved.status is StructuredResolutionStatus.RESOLVED
    assert resolved.resolved_record is not None and resolved.resolved_record.is_current is None and resolved.resolved_record.end_date is None
    assert rejected.status is StructuredResolutionStatus.REJECTED and rejected.resolved_record is None
    assert rejected.audit.field_audits[0].original_proposed_value == candidate.company


def test_reject_verified_and_leave_user_provided_fields_preserve_their_distinct_semantics() -> None:
    candidate = create_work_experience_candidate(
        origin=origin(),
        company=text("ACME", VerificationStatus.VERIFIED),
        title=ProvenancedText(value="Engineer", verification_status=VerificationStatus.USER_PROVIDED, value_source=source(SourceType.USER_INPUT, "prior:confirmation")),
    )
    result = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.REJECT),
            title=TextFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED),
        ),
    )

    assert result.status is StructuredResolutionStatus.PARTIALLY_RESOLVED
    assert result.resolved_record is not None
    assert result.resolved_record.company is None
    assert result.resolved_record.title is not None
    assert result.resolved_record.title.verification_status is VerificationStatus.USER_PROVIDED


def test_education_confirmation_is_field_level_and_has_its_own_minimum_identity() -> None:
    candidate = create_education_candidate(origin=origin("page:1:education-group:1"), institution=text("Y University"), field_of_study=text("Mechanical Engineering"))
    partial = resolve_education_candidate(
        candidate,
        EducationFieldDecisions(institution=TextFieldDecision(action=StructuredFieldAction.ACCEPT)),
        user_input_reference="structured-review:education:1",
    )
    complete = resolve_education_candidate(
        candidate,
        EducationFieldDecisions(
            institution=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            degree=TextFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value="Bachelor of Engineering"),
        ),
        user_input_reference="structured-review:education:2",
    )
    rejected = resolve_education_candidate(candidate, EducationFieldDecisions(), whole_record_action=WholeRecordAction.REJECT_RECORD)

    assert partial.status is StructuredResolutionStatus.PARTIALLY_RESOLVED
    assert complete.status is StructuredResolutionStatus.RESOLVED
    assert complete.resolved_record is not None and complete.resolved_record.degree is not None
    assert complete.resolved_record.degree.value == "Bachelor of Engineering"
    assert complete.resolved_record.field_of_study is not None and complete.resolved_record.field_of_study.is_claim_usable is False
    assert rejected.status is StructuredResolutionStatus.REJECTED and rejected.resolved_record is None


def test_unicode_correction_and_same_input_are_deterministic() -> None:
    candidate = work_candidate()
    decisions = WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        title=TextFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value="Kıdemli Mühendis"),
    )
    first = resolve_work_experience_candidate(candidate, decisions, user_input_reference="structured-review:work:unicode")
    second = resolve_work_experience_candidate(candidate, decisions, user_input_reference="structured-review:work:unicode")

    assert first == second
    assert first.resolved_record is not None and first.resolved_record.title is not None
    assert first.resolved_record.title.value == "Kıdemli Mühendis"
    with pytest.raises(ValidationError):
        candidate.company = None
    with pytest.raises(ValidationError):
        first.audit.field_audits = ()


def test_results_are_immutable_serializable_and_do_not_touch_legacy_or_atomic_flows() -> None:
    candidate = work_candidate()
    result = resolve_work_experience_candidate(candidate, WorkExperienceFieldDecisions(), whole_record_action=WholeRecordAction.REJECT_RECORD)

    assert type(result).model_validate(result.model_dump(mode="json")) == result
    with pytest.raises(ValidationError):
        result.status = StructuredResolutionStatus.RESOLVED
    assert not hasattr(candidate, "facts")
    assert "resolve_candidate" not in inspect.getsource(structured_service)
    assert WorkExperience.model_fields["company"].annotation is str
    assert Education.model_fields["institution"].annotation is str
    assert CareerProfile.model_fields["work_experiences"].annotation is not None
    assert assemble_verified_career_profile(CareerProfile(), ()).profile == CareerProfile()
    assert assess_career_profile_readiness(CareerProfile()).status.value == "blocked"
    assert ConfirmationAction.ACCEPT.value == "accept"
    assert callable(resolve_candidate)

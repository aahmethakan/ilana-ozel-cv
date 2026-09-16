import pytest
from pydantic import ValidationError

from app.confirmation.structured import (
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
from app.domain.career import CareerDate, CareerProfile, FactSource, ProvenancedCareerDate, ProvenancedText, SourceType, VerificationStatus
from app.domain.career.profile import Education, WorkExperience
from app.extraction.career import UnresolvedEvidence
from app.services.career_profile_assembly import assemble_verified_career_profile
from app.services.profile_readiness import assess_career_profile_readiness
from app.services.structured_profile import (
    StructuredCareerProfile,
    StructuredEducationEntry,
    StructuredWorkExperienceEntry,
    assemble_structured_career_profile,
)
from app.services.structured_profile import service as structured_profile_service


def source(reference: str) -> FactSource:
    return FactSource(source_type=SourceType.MASTER_CV, reference=reference, original_text="Synthetic source evidence")


def inferred_text(value: str, reference: str) -> ProvenancedText:
    return ProvenancedText(value=value, verification_status=VerificationStatus.INFERRED_UNVERIFIED, value_source=source(reference), evidence_sources=(source(reference),))


def inferred_date(year: int, reference: str) -> ProvenancedCareerDate:
    return ProvenancedCareerDate(value=CareerDate(year=year), verification_status=VerificationStatus.INFERRED_UNVERIFIED, value_source=source(reference), evidence_sources=(source(reference),))


def origin(reference: str) -> StructuredRecordOrigin:
    return StructuredRecordOrigin(evidence_sources=(source(reference),))


def work_result(reference: str = "page:1:work:1", title: str = "Engineer", *, partial: bool = False):
    candidate = create_work_experience_candidate(
        origin=origin(reference),
        company=inferred_text("ACME", reference),
        title=inferred_text(title, reference),
        start_date=inferred_date(2021, reference),
    )
    decisions = WorkExperienceFieldDecisions(
        company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        title=TextFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED if partial else StructuredFieldAction.ACCEPT),
    )
    return resolve_work_experience_candidate(candidate, decisions, user_input_reference=f"review:{reference}")


def education_result(reference: str = "page:1:education:1", *, partial: bool = False):
    candidate = create_education_candidate(
        origin=origin(reference),
        institution=inferred_text("Y University", reference),
        field_of_study=inferred_text("Mechanical Engineering", reference),
    )
    decisions = EducationFieldDecisions(
        institution=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
        field_of_study=TextFieldDecision(action=StructuredFieldAction.LEAVE_UNRESOLVED if partial else StructuredFieldAction.ACCEPT),
    )
    return resolve_education_candidate(candidate, decisions, user_input_reference=f"review:{reference}")


def test_empty_profile_and_resolved_or_partial_entries_are_valid() -> None:
    work = work_result()
    partial_work = work_result("page:1:work:2", partial=True)
    education = education_result()
    partial_education = education_result("page:1:education:2", partial=True)

    result = assemble_structured_career_profile(work_results=(work, partial_work), education_results=(education, partial_education))

    assert StructuredCareerProfile() == assemble_structured_career_profile().profile
    assert [entry.resolution_status for entry in result.profile.work_experiences] == [StructuredResolutionStatus.RESOLVED, StructuredResolutionStatus.PARTIALLY_RESOLVED]
    assert [entry.resolution_status for entry in result.profile.education] == [StructuredResolutionStatus.RESOLVED, StructuredResolutionStatus.PARTIALLY_RESOLVED]
    assert result.profile.work_experiences[1].record.has_minimum_trusted_identity is False


def test_rejected_invalid_and_missing_records_are_not_admitted() -> None:
    candidate = create_work_experience_candidate(origin=origin("page:1:work:rejected"), company=inferred_text("ACME", "page:1:work:rejected"))
    rejected = resolve_work_experience_candidate(candidate, WorkExperienceFieldDecisions(), whole_record_action=WholeRecordAction.REJECT_RECORD)
    invalid = resolve_work_experience_candidate(
        candidate,
        WorkExperienceFieldDecisions(company=TextFieldDecision(action=StructuredFieldAction.ACCEPT)),
    )
    missing = invalid.model_copy(update={"status": StructuredResolutionStatus.RESOLVED, "resolved_record": None})
    result = assemble_structured_career_profile(work_results=(rejected, invalid, missing))

    assert result.profile.work_experiences == ()
    assert [item.reason_code for item in result.skipped_records] == ["rejected_resolution", "invalid_resolution", "missing_resolved_record"]


def test_provenance_dates_and_record_identity_are_preserved_without_flattening() -> None:
    resolution = work_result()
    result = assemble_structured_career_profile(work_results=(resolution,))
    entry = result.profile.work_experiences[0]

    assert entry.record.record_id == resolution.candidate.record_id
    assert entry.candidate_id == resolution.candidate.candidate_id
    assert entry.record.company is not None and entry.record.company.value_source.source_type is SourceType.USER_INPUT
    assert entry.record.company.evidence_sources == (source("page:1:work:1"),)
    assert entry.record.start_date is not None and entry.record.start_date.value == CareerDate(year=2021)
    assert entry.record.start_date.is_claim_usable is False
    assert result.applied_record_ids == (entry.record.record_id,)


def test_exact_duplicates_deduplicate_but_conflicting_same_identity_is_not_admitted() -> None:
    first = work_result()
    exact = work_result()
    conflicting = work_result(title="Senior Engineer")
    result = assemble_structured_career_profile(work_results=(first, exact, conflicting))

    assert result.profile.work_experiences == ()
    assert result.applied_record_ids == ()
    assert result.conflicts[0].reason_code == "duplicate_record_id_conflicting_state"
    assert result.conflicts[0].candidate_ids == (first.candidate.candidate_id, exact.candidate.candidate_id, conflicting.candidate.candidate_id)


def test_same_current_state_with_different_candidate_lineage_is_a_conflict() -> None:
    first = work_result()
    alternate_candidate = create_work_experience_candidate(
        origin=origin("page:1:work:1"),
        company=inferred_text("ACME", "page:1:work:1"),
        title=inferred_text("Engineer", "page:1:work:1"),
        location=inferred_text("Istanbul", "page:1:work:1"),
        start_date=inferred_date(2021, "page:1:work:1"),
    )
    alternate = resolve_work_experience_candidate(
        alternate_candidate,
        WorkExperienceFieldDecisions(
            company=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            title=TextFieldDecision(action=StructuredFieldAction.ACCEPT),
            location=TextFieldDecision(action=StructuredFieldAction.REJECT),
        ),
        user_input_reference="review:page:1:work:1",
    )

    assert alternate.resolved_record == first.resolved_record
    assert alternate.candidate.candidate_id != first.candidate.candidate_id
    result = assemble_structured_career_profile(work_results=(first, alternate))

    assert result.profile.work_experiences == ()
    assert result.applied_record_ids == ()
    assert result.conflicts[0].reason_code == "duplicate_record_id_conflicting_lineage"
    assert result.conflicts[0].candidate_ids == (first.candidate.candidate_id, alternate.candidate.candidate_id)


def test_conflicts_are_order_independent_and_remove_the_entire_record_group() -> None:
    first = work_result()
    conflicting = work_result(title="Senior Engineer")
    unrelated = work_result("page:1:work:unrelated")

    forward = assemble_structured_career_profile(work_results=(first, conflicting, unrelated))
    reverse = assemble_structured_career_profile(work_results=(conflicting, first, unrelated))

    assert [entry.record.record_id for entry in forward.profile.work_experiences] == [unrelated.candidate.record_id]
    assert [entry.record.record_id for entry in reverse.profile.work_experiences] == [unrelated.candidate.record_id]
    assert forward.conflicts[0].record_id == reverse.conflicts[0].record_id == first.candidate.record_id
    assert forward.conflicts[0].reason_code == reverse.conflicts[0].reason_code == "duplicate_record_id_conflicting_state"


def test_distinct_record_ids_and_input_order_are_preserved_without_fuzzy_merging() -> None:
    first = work_result("page:1:work:1")
    second = work_result("page:1:work:2")
    forward = assemble_structured_career_profile(work_results=(first, second))
    reverse = assemble_structured_career_profile(work_results=(second, first))

    assert len(forward.profile.work_experiences) == 2
    assert [entry.record.record_id for entry in forward.profile.work_experiences] == [first.candidate.record_id, second.candidate.record_id]
    assert [entry.record.record_id for entry in reverse.profile.work_experiences] == [second.candidate.record_id, first.candidate.record_id]
    assert set(forward.applied_record_ids) == set(reverse.applied_record_ids)


def test_serialization_immutability_and_strict_profile_schema() -> None:
    result = assemble_structured_career_profile(work_results=(work_result(),), education_results=(education_result(),))

    assert type(result).model_validate(result.model_dump(mode="json")) == result
    with pytest.raises(ValidationError):
        result.profile.work_experiences = ()
    with pytest.raises(ValidationError):
        StructuredCareerProfile(unexpected=True)


def test_entries_reject_impossible_status_and_identity_combinations() -> None:
    resolved_work = work_result()
    partial_work = work_result("page:1:work:partial", partial=True)
    resolved_education = education_result()
    partial_education = education_result("page:1:education:partial", partial=True)

    with pytest.raises(ValidationError):
        StructuredWorkExperienceEntry(
            record=resolved_work.resolved_record,
            resolution_status=StructuredResolutionStatus.PARTIALLY_RESOLVED,
            candidate_id=resolved_work.candidate.candidate_id,
        )
    with pytest.raises(ValidationError):
        StructuredWorkExperienceEntry(
            record=partial_work.resolved_record,
            resolution_status=StructuredResolutionStatus.RESOLVED,
            candidate_id=partial_work.candidate.candidate_id,
        )
    with pytest.raises(ValidationError):
        StructuredEducationEntry(
            record=resolved_education.resolved_record,
            resolution_status=StructuredResolutionStatus.REJECTED,
            candidate_id=resolved_education.candidate.candidate_id,
        )
    with pytest.raises(ValidationError):
        StructuredEducationEntry(
            record=partial_education.resolved_record,
            resolution_status=StructuredResolutionStatus.RESOLVED,
            candidate_id=partial_education.candidate.candidate_id,
        )
    with pytest.raises(ValidationError):
        StructuredWorkExperienceEntry(
            record=resolved_education.resolved_record,
            resolution_status=StructuredResolutionStatus.RESOLVED,
            candidate_id=resolved_education.candidate.candidate_id,
        )


def test_existing_legacy_and_downstream_layers_remain_separate() -> None:
    source_text = inspect_source = __import__("inspect").getsource(structured_profile_service)

    assert "assemble_verified_career_profile" not in source_text
    assert "assess_career_profile_readiness" not in source_text
    assert "WorkExperience(" not in source_text and "Education(" not in source_text
    assert WorkExperience.model_fields["company"].annotation is str
    assert Education.model_fields["institution"].annotation is str
    assert CareerProfile.model_fields["work_experiences"].annotation is not None
    assert assemble_verified_career_profile(CareerProfile(), ()).profile == CareerProfile()
    assert assess_career_profile_readiness(CareerProfile()).status.value == "blocked"
    assert UnresolvedEvidence(block_reference="page:1:block:1", reason="synthetic").block_reference == "page:1:block:1"


def test_assembly_outcomes_are_immutable() -> None:
    candidate = create_work_experience_candidate(origin=origin("page:1:work:rejected"), company=inferred_text("ACME", "page:1:work:rejected"))
    rejected = resolve_work_experience_candidate(candidate, WorkExperienceFieldDecisions(), whole_record_action=WholeRecordAction.REJECT_RECORD)
    first = work_result()
    conflicting = work_result(title="Senior Engineer")
    result = assemble_structured_career_profile(work_results=(rejected, first, conflicting))

    with pytest.raises(ValidationError):
        result.applied_record_ids = ()
    with pytest.raises(ValidationError):
        result.skipped_records[0].reason_code = "changed"
    with pytest.raises(ValidationError):
        result.conflicts[0].reason_code = "changed"

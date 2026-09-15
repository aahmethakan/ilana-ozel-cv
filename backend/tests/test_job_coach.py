import inspect

import pytest
from pydantic import ValidationError

from app.confirmation.career import ConfirmationAction, resolve_candidate
from app.domain.career import CareerFact, CareerProfile, FactSource, LanguageSkill, SourceType, VerificationStatus
from app.domain.job import (
    JobProfile,
    JobRequirement,
    RequirementCategory,
    RequirementExplicitness,
    RequirementImportance,
)
from app.services.career_profile_assembly import assemble_verified_career_profile
from app.services.coach_answer_processing import CoachAnswer, CoachAnswerStatus, process_coach_answer
from app.services.job_coach import JobCoachContext, generate_job_specific_coach_questions
from app.services.job_coach import service as coach_service
from app.services.job_match import JobMatchResult, RequirementMatchResult, RequirementMatchStatus, match_job_to_profile
from app.services.job_match_score import calculate_job_match_score


def requirement(
    text: str,
    category: RequirementCategory = RequirementCategory.SKILL,
    importance: RequirementImportance = RequirementImportance.REQUIRED,
    identifier: str | None = None,
    reference: str = "job:line:1",
) -> JobRequirement:
    return JobRequirement(
        requirement_id=identifier or f"job:{category.value}:{text}",
        category=category,
        text=text,
        importance=importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source_references=(reference,),
        source_texts=(text,),
    )


def match_item(item: JobRequirement, status: RequirementMatchStatus) -> RequirementMatchResult:
    return RequirementMatchResult(
        requirement=item,
        status=status,
        matched_evidence_references=(),
        reason_code="synthetic",
        explanation="Synthetic match result.",
    )


def coach(profile: JobProfile, *results: RequirementMatchResult, context: JobCoachContext | None = None):
    return generate_job_specific_coach_questions(profile, JobMatchResult(requirement_results=results), context=context)


@pytest.mark.parametrize(
    ("importance", "priority"),
    [
        (RequirementImportance.REQUIRED, "high"),
        (RequirementImportance.PREFERRED, "medium"),
        (RequirementImportance.UNKNOWN, "medium"),
    ],
)
def test_not_evidenced_skill_uses_importance_priority(importance: RequirementImportance, priority: str) -> None:
    item = requirement("Problem Solving", importance=importance)
    result = coach(JobProfile(requirements=(item,)), match_item(item, RequirementMatchStatus.NOT_EVIDENCED))

    question = result.questions[0]
    assert question.question.category.value == "skill"
    assert question.question.priority.value == priority
    assert question.requirement_id == item.requirement_id
    assert question.job_source_references == ("job:line:1",)
    assert "candidate lacks" not in question.question.reason.casefold()


@pytest.mark.parametrize(
    ("category", "text", "expected_gap_category"),
    [
        (RequirementCategory.TOOL, "SAP", "tool"),
        (RequirementCategory.LANGUAGE, "German", "language"),
        (RequirementCategory.CERTIFICATION, "PMP", "certification"),
    ],
)
def test_supported_not_evidenced_categories_generate_compatible_questions(category: RequirementCategory, text: str, expected_gap_category: str) -> None:
    item = requirement(text, category)
    result = coach(JobProfile(requirements=(item,)), match_item(item, RequirementMatchStatus.NOT_EVIDENCED))

    assert result.questions[0].question.category.value == expected_gap_category
    assert result.questions[0].match_status is RequirementMatchStatus.NOT_EVIDENCED


def test_matched_and_not_evaluable_requirements_do_not_generate_questions() -> None:
    matched = requirement("SAP")
    education = requirement("Bachelor's degree", RequirementCategory.EDUCATION, identifier="job:education")
    result = coach(
        JobProfile(requirements=(matched, education)),
        match_item(matched, RequirementMatchStatus.MATCHED),
        match_item(education, RequirementMatchStatus.NOT_EVALUABLE),
    )

    assert result.questions == ()
    assert result.skipped_requirements[0].reason_code == "not_evaluable_requirement"


def test_language_partial_generates_unanchored_proficiency_clarification() -> None:
    item = requirement("English B2", RequirementCategory.LANGUAGE)
    result = coach(JobProfile(requirements=(item,)), match_item(item, RequirementMatchStatus.PARTIAL))
    question = result.questions[0]

    assert question.question.category.value == "language"
    assert question.match_status is RequirementMatchStatus.PARTIAL
    assert "B2" not in question.question.question_text
    assert "personally state" in question.question.question_text

    answer = process_coach_answer(question.question, CoachAnswer(question_id=question.question.question_id, answer_text="English - B1"))
    assert answer.status is CoachAnswerStatus.CANDIDATE_CREATED
    assert answer.candidate is not None and answer.candidate.is_claim_usable is False


def test_non_language_partial_and_unsupported_categories_are_deferred() -> None:
    partial_skill = requirement("SAP")
    experience = requirement("3 years experience", RequirementCategory.EXPERIENCE, identifier="job:experience")
    result = coach(
        JobProfile(requirements=(partial_skill, experience)),
        match_item(partial_skill, RequirementMatchStatus.PARTIAL),
        match_item(experience, RequirementMatchStatus.NOT_EVIDENCED),
    )

    assert result.questions == ()
    assert {item.reason_code for item in result.skipped_requirements} == {"unsupported_partial_category", "unsupported_category"}


def test_order_limit_and_duplicate_identity_are_deterministic() -> None:
    preferred = requirement("PMP", RequirementCategory.CERTIFICATION, RequirementImportance.PREFERRED, identifier="job:preferred", reference="job:line:2")
    high_first = requirement("SAP", RequirementCategory.TOOL, RequirementImportance.REQUIRED, identifier="job:high-1")
    high_second = requirement("Excel", RequirementCategory.TOOL, RequirementImportance.REQUIRED, identifier="job:high-2", reference="job:line:3")
    duplicate = high_first.model_copy(update={"source_references": ("job:line:4",)})
    profile = JobProfile(requirements=(preferred, high_first, high_second, duplicate))
    result = coach(
        profile,
        match_item(preferred, RequirementMatchStatus.NOT_EVIDENCED),
        match_item(high_first, RequirementMatchStatus.NOT_EVIDENCED),
        match_item(high_second, RequirementMatchStatus.NOT_EVIDENCED),
        context=JobCoachContext(max_questions=2),
    )

    assert [item.requirement_text for item in result.questions] == ["SAP", "Excel"]
    assert result.eligible_count == 3
    assert result.generated_count == 2 and result.truncated_count == 1


def test_default_limit_and_counts_are_bounded_and_reconcile() -> None:
    requirements = tuple(
        requirement(f"Tool {index}", RequirementCategory.TOOL, identifier=f"job:tool:{index}")
        for index in range(7)
    )
    result = coach(
        JobProfile(requirements=requirements),
        *(match_item(item, RequirementMatchStatus.NOT_EVIDENCED) for item in requirements),
    )

    assert len(result.questions) == 5
    assert (result.eligible_count, result.generated_count, result.truncated_count) == (7, 5, 2)


@pytest.mark.parametrize("max_questions", (0, 9))
def test_question_limit_is_constrained_to_the_supported_range(max_questions: int) -> None:
    with pytest.raises(ValidationError):
        JobCoachContext(max_questions=max_questions)


def test_distinct_requirement_ids_are_not_semantically_deduplicated_and_dangling_match_is_visible() -> None:
    sap = requirement("SAP", identifier="job:sap")
    sap_erp = requirement("SAP ERP", identifier="job:sap-erp", reference="job:line:2")
    dangling = requirement("Excel", identifier="job:dangling", reference="job:line:9")
    result = coach(
        JobProfile(requirements=(sap, sap_erp)),
        match_item(sap, RequirementMatchStatus.NOT_EVIDENCED),
        match_item(sap_erp, RequirementMatchStatus.NOT_EVIDENCED),
        match_item(dangling, RequirementMatchStatus.NOT_EVIDENCED),
    )

    assert [item.requirement_text for item in result.questions] == ["SAP", "SAP ERP"]
    assert result.skipped_requirements[0].reason_code == "dangling_match_requirement"


def test_tool_end_to_end_question_answer_confirmation_assembly_rematch_and_rescore() -> None:
    item = requirement("SAP", RequirementCategory.TOOL)
    job = JobProfile(requirements=(item,))
    initial_match = match_job_to_profile(job, CareerProfile())
    coach_result = generate_job_specific_coach_questions(job, initial_match)
    answer = process_coach_answer(coach_result.questions[0].question, CoachAnswer(question_id=coach_result.questions[0].question.question_id, answer_text="SAP"))
    assert answer.candidate is not None and answer.candidate.candidate_type.value == "tool"
    resolution = resolve_candidate(answer.candidate, ConfirmationAction.ACCEPT)
    assert resolution.promoted_fact is not None
    assembled = assemble_verified_career_profile(CareerProfile(), (resolution.promoted_fact,)).profile
    rematch = match_job_to_profile(job, assembled)
    rescored = calculate_job_match_score(rematch)

    assert rematch.requirement_results[0].status is RequirementMatchStatus.MATCHED
    assert rescored.match_score == 100


def test_skill_end_to_end_and_certification_alternate_answer_do_not_force_job_keyword() -> None:
    skill_item = requirement("Problem Solving")
    certification_item = requirement("PMP", RequirementCategory.CERTIFICATION, identifier="job:pmp")
    job = JobProfile(requirements=(skill_item, certification_item))
    initial = match_job_to_profile(job, CareerProfile())
    questions = generate_job_specific_coach_questions(job, initial).questions
    by_id = {item.requirement_id: item for item in questions}

    skill_answer = process_coach_answer(by_id[skill_item.requirement_id].question, CoachAnswer(question_id=by_id[skill_item.requirement_id].question.question_id, answer_text="Problem Solving"))
    cert_answer = process_coach_answer(by_id[certification_item.requirement_id].question, CoachAnswer(question_id=by_id[certification_item.requirement_id].question.question_id, answer_text="PRINCE2"))
    assert skill_answer.candidate is not None and cert_answer.candidate is not None
    skill_fact = resolve_candidate(skill_answer.candidate, ConfirmationAction.ACCEPT).promoted_fact
    cert_fact = resolve_candidate(cert_answer.candidate, ConfirmationAction.ACCEPT).promoted_fact
    assert skill_fact is not None and cert_fact is not None
    assembled = assemble_verified_career_profile(CareerProfile(), (skill_fact, cert_fact)).profile
    rematch = match_job_to_profile(job, assembled)

    assert rematch.requirement_results[0].status is RequirementMatchStatus.MATCHED
    assert rematch.requirement_results[1].status is RequirementMatchStatus.NOT_EVIDENCED
    assert [item.name for item in assembled.certifications] == ["PRINCE2"]


def test_certification_correction_rejection_inference_and_duplicate_handling_are_safe() -> None:
    item = requirement("PMP", RequirementCategory.CERTIFICATION)
    question = coach(JobProfile(requirements=(item,)), match_item(item, RequirementMatchStatus.NOT_EVIDENCED)).questions[0].question
    answer = process_coach_answer(question, CoachAnswer(question_id=question.question_id, answer_text="PMP"))
    assert answer.candidate is not None

    corrected = resolve_candidate(answer.candidate, ConfirmationAction.CORRECT, correction="PRINCE2")
    rejected = resolve_candidate(answer.candidate, ConfirmationAction.REJECT)
    assert corrected.promoted_fact is not None
    assert corrected.promoted_fact.certifications == ("PRINCE2",)
    assert rejected.promoted_fact is None

    inferred = CareerFact(
        statement="PMP",
        verification_status=VerificationStatus.INFERRED_UNVERIFIED,
        source=FactSource(source_type=SourceType.SYSTEM_INFERENCE, reference="synthetic:inference"),
        certifications=("PMP",),
    )
    assembled = assemble_verified_career_profile(CareerProfile(), (corrected.promoted_fact, corrected.promoted_fact, inferred))

    assert [item.name for item in assembled.profile.certifications] == ["PRINCE2"]
    assert {item.reason_code for item in assembled.skipped_facts} == {"duplicate_certification", "untrusted_verification_status"}
    serialized = corrected.promoted_fact.model_dump(mode="json")
    assert serialized["certifications"] == ["PRINCE2"]


def test_inputs_and_results_are_immutable_deterministic_and_without_rematching_or_score_logic() -> None:
    item = requirement("SAP")
    profile = JobProfile(requirements=(item,))
    match_result = JobMatchResult(requirement_results=(match_item(item, RequirementMatchStatus.NOT_EVIDENCED),))
    first = generate_job_specific_coach_questions(profile, match_result)
    second = generate_job_specific_coach_questions(profile, match_result)

    assert first == second
    assert profile.requirements == (item,)
    assert match_result.requirement_results[0].status is RequirementMatchStatus.NOT_EVIDENCED
    with pytest.raises(ValidationError):
        first.questions = ()
    source = inspect.getsource(coach_service)
    assert "match_job_to_profile" not in source
    assert "calculate_job_match_score" not in source
    assert "app.ai" not in source and "embedding" not in source

import pytest
from pydantic import ValidationError

from app.ai.career import AIConfidence, CandidateType, CareerFactCandidate
from app.ai.career.validation import can_auto_promote
from app.confirmation.career import ConfirmationAction, resolve_candidate
from app.confirmation.career.schemas import ResolutionStatus
from app.domain.career import CareerFact, CareerProfile, FactSource, SourceType, VerificationStatus
from app.domain.job import (
    JobProfile,
    JobRequirement,
    RequirementCategory,
    RequirementExplicitness,
    RequirementImportance,
)
from app.services.career_gap_analysis import CoachQuestion, GapCategory, GapPriority
from app.services.career_gap_analysis.schemas import AnswerType
from app.services.career_profile_assembly import assemble_verified_career_profile
from app.services.coach_answer_processing import CoachAnswer, CoachAnswerStatus, process_coach_answer
from app.services.job_match import RequirementMatchStatus, match_job_to_profile


def question(category: GapCategory, question_id: str) -> CoachQuestion:
    return CoachQuestion(
        question_id=question_id,
        category=category,
        question_text="Synthetic evidence question",
        reason="No trusted evidence is currently recorded.",
        target_section="skills",
        priority=GapPriority.HIGH,
        missing_signal="synthetic",
        answer_type=AnswerType.YES_NO_DETAILS,
    )


def requirement(category: RequirementCategory, text: str = "SAP") -> JobRequirement:
    return JobRequirement(
        requirement_id=f"job:{category.value}:{text}",
        category=category,
        text=text,
        importance=RequirementImportance.REQUIRED,
        explicitness=RequirementExplicitness.EXPLICIT,
        source_references=("job:line:1",),
        source_texts=(text,),
    )


def confirmed_fact(category: GapCategory, value: str = "SAP") -> CareerFact:
    answer_result = process_coach_answer(question(category, f"{category.value}-question"), CoachAnswer(question_id=f"{category.value}-question", answer_text=value))
    assert answer_result.status is CoachAnswerStatus.CANDIDATE_CREATED
    assert answer_result.candidate is not None
    resolution = resolve_candidate(answer_result.candidate, ConfirmationAction.ACCEPT)
    assert resolution.status is ResolutionStatus.PROMOTED
    assert resolution.promoted_fact is not None
    return resolution.promoted_fact


def test_distinct_skill_and_tool_enums_exist() -> None:
    assert CandidateType.SKILL.value == "skill"
    assert CandidateType.TOOL.value == "tool"
    assert GapCategory.SKILL.value == "skill"
    assert GapCategory.TOOL.value == "tool"


def test_skill_and_tool_answers_create_separate_untrusted_candidates() -> None:
    skill_result = process_coach_answer(question(GapCategory.SKILL, "skill-question"), CoachAnswer(question_id="skill-question", answer_text="Problem Solving"))
    tool_result = process_coach_answer(question(GapCategory.TOOL, "tool-question"), CoachAnswer(question_id="tool-question", answer_text="SAP"))

    assert skill_result.candidate is not None and skill_result.candidate.candidate_type is CandidateType.SKILL
    assert tool_result.candidate is not None and tool_result.candidate.candidate_type is CandidateType.TOOL
    assert tool_result.candidate.verification_status is VerificationStatus.INFERRED_UNVERIFIED
    assert tool_result.candidate.is_claim_usable is False


def test_tool_end_to_end_preserves_tool_boundary_and_user_input_provenance() -> None:
    tool_fact = confirmed_fact(GapCategory.TOOL)
    assembled = assemble_verified_career_profile(CareerProfile(), (tool_fact,)).profile
    tool_match = match_job_to_profile(JobProfile(requirements=(requirement(RequirementCategory.TOOL),)), assembled).requirement_results[0]
    skill_match = match_job_to_profile(JobProfile(requirements=(requirement(RequirementCategory.SKILL),)), assembled).requirement_results[0]

    assert tool_fact.skills == () and tool_fact.tools == ("SAP",)
    assert tool_fact.verification_status is VerificationStatus.USER_PROVIDED
    assert tool_fact.source.source_type is SourceType.USER_INPUT
    assert tool_fact.source.reference == "coach_question:tool-question"
    assert assembled.tools == (tool_fact,) and assembled.skills == ()
    assert tool_match.status is RequirementMatchStatus.MATCHED
    assert tool_match.matched_evidence_references == ("coach_question:tool-question",)
    assert skill_match.status is RequirementMatchStatus.NOT_EVIDENCED


def test_skill_end_to_end_preserves_skill_boundary() -> None:
    skill_fact = confirmed_fact(GapCategory.SKILL, "Problem Solving")
    assembled = assemble_verified_career_profile(CareerProfile(), (skill_fact,)).profile
    skill_match = match_job_to_profile(JobProfile(requirements=(requirement(RequirementCategory.SKILL, "Problem Solving"),)), assembled).requirement_results[0]
    tool_match = match_job_to_profile(JobProfile(requirements=(requirement(RequirementCategory.TOOL, "Problem Solving"),)), assembled).requirement_results[0]

    assert skill_fact.skills == ("Problem Solving",) and skill_fact.tools == ()
    assert assembled.skills == (skill_fact,) and assembled.tools == ()
    assert skill_match.status is RequirementMatchStatus.MATCHED
    assert tool_match.status is RequirementMatchStatus.NOT_EVIDENCED


def test_skill_and_tool_same_text_coexist_and_exact_tool_dedup_is_separate() -> None:
    skill_fact = confirmed_fact(GapCategory.SKILL)
    tool_fact = confirmed_fact(GapCategory.TOOL)
    duplicate_tool = tool_fact.model_copy(update={"source": FactSource(source_type=SourceType.USER_INPUT, reference="coach_question:other", original_text="SAP")})
    sap_erp_tool = tool_fact.model_copy(update={"statement": "SAP ERP", "tools": ("SAP ERP",)})
    assembled = assemble_verified_career_profile(CareerProfile(), (skill_fact, tool_fact, duplicate_tool, sap_erp_tool))

    assert [item.statement for item in assembled.profile.skills] == ["SAP"]
    assert [item.statement for item in assembled.profile.tools] == ["SAP", "SAP ERP"]
    assert any(item.reason_code == "duplicate_tool" for item in assembled.skipped_facts)
    skill_match = match_job_to_profile(JobProfile(requirements=(requirement(RequirementCategory.SKILL),)), assembled.profile).requirement_results[0]
    tool_match = match_job_to_profile(JobProfile(requirements=(requirement(RequirementCategory.TOOL),)), assembled.profile).requirement_results[0]
    assert skill_match.status is RequirementMatchStatus.MATCHED
    assert tool_match.status is RequirementMatchStatus.MATCHED


def test_unverified_tool_fact_never_enters_trusted_profile() -> None:
    unverified_tool = CareerFact(
        statement="SAP",
        tools=("SAP",),
        verification_status=VerificationStatus.INFERRED_UNVERIFIED,
        source=FactSource(source_type=SourceType.SYSTEM_INFERENCE, reference="inference:1", original_text="SAP"),
    )
    assembled = assemble_verified_career_profile(CareerProfile(), (unverified_tool,))

    assert assembled.profile.tools == ()
    assert assembled.skipped_facts[0].reason_code == "untrusted_verification_status"


def test_ai_style_tool_candidate_remains_unverified_and_cannot_auto_promote() -> None:
    candidate = CareerFactCandidate(
        candidate_type=CandidateType.TOOL,
        proposed_statement="SAP",
        evidence_references=("page:1:block:1",),
        confidence=AIConfidence.HIGH,
    )

    assert candidate.verification_status is VerificationStatus.INFERRED_UNVERIFIED
    assert candidate.requires_user_confirmation is True
    assert candidate.is_claim_usable is False
    assert can_auto_promote(candidate) is False


def test_tool_correct_and_reject_preserve_category_and_fact_boundary() -> None:
    answer_result = process_coach_answer(question(GapCategory.TOOL, "tool-question"), CoachAnswer(question_id="tool-question", answer_text="SAP"))
    assert answer_result.candidate is not None
    corrected = resolve_candidate(answer_result.candidate, ConfirmationAction.CORRECT, correction="Siemens TIA Portal")
    rejected = resolve_candidate(answer_result.candidate, ConfirmationAction.REJECT)

    assert corrected.promoted_fact is not None
    assert corrected.promoted_fact.tools == ("Siemens TIA Portal",)
    assert corrected.promoted_fact.skills == ()
    assert corrected.audit.user_correction == "Siemens TIA Portal"
    assert rejected.status is ResolutionStatus.REJECTED and rejected.promoted_fact is None


def test_profile_tools_are_preserved_by_assembly_and_serialization_round_trip() -> None:
    tool_fact = confirmed_fact(GapCategory.TOOL)
    base = CareerProfile(tools=(tool_fact,))
    result = assemble_verified_career_profile(base, ())
    round_trip = CareerProfile.model_validate(base.model_dump(mode="json"))

    assert result.profile.tools == (tool_fact,)
    assert round_trip.tools == (tool_fact,)
    assert CareerProfile.model_validate({}).tools == ()


def test_generic_and_negative_answers_remain_safe_for_skill_and_tool() -> None:
    generic = process_coach_answer(question(GapCategory.SKILL, "skill-question"), CoachAnswer(question_id="skill-question", answer_text="Yes"))
    negative = process_coach_answer(question(GapCategory.TOOL, "tool-question"), CoachAnswer(question_id="tool-question", answer_text="No"))

    assert generic.status is CoachAnswerStatus.DEFERRED and generic.candidate is None
    assert negative.status is CoachAnswerStatus.ANSWERED_NO and negative.candidate is None


def test_tool_candidate_and_profile_models_are_immutable() -> None:
    fact = confirmed_fact(GapCategory.TOOL)
    profile = assemble_verified_career_profile(CareerProfile(), (fact,)).profile

    with pytest.raises(ValidationError):
        fact.tools = ("SAP ERP",)
    with pytest.raises(ValidationError):
        profile.tools = ()

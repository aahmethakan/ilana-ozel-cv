import inspect

from app.confirmation.career import ConfirmationAction, resolve_candidate
from app.domain.career import SourceType, VerificationStatus
from app.services.career_gap_analysis import CoachQuestion, GapCategory, GapPriority
from app.services.career_gap_analysis.schemas import AnswerType
from app.services.coach_answer_processing import CoachAnswer, CoachAnswerStatus, process_coach_answer
from app.services.coach_answer_processing import service as answer_service


def question(category: GapCategory, *, question_id: str = "question-1", refs: tuple[str, ...] = ("page:1:block:1",)) -> CoachQuestion:
    return CoachQuestion(
        question_id=question_id,
        category=category,
        question_text="Synthetic coach question",
        reason="Not currently evidenced.",
        target_section="skills",
        priority=GapPriority.MEDIUM,
        evidence_references=refs,
        missing_signal="synthetic_missing_signal",
        answer_type=AnswerType.YES_NO_DETAILS,
    )


def process(category: GapCategory, text: str, **kwargs):
    item = question(category, **kwargs)
    return item, CoachAnswer(question_id=item.question_id, answer_text=text), process_coach_answer(item, CoachAnswer(question_id=item.question_id, answer_text=text))


def test_question_mismatch_blank_negative_and_generic_answers_are_safe() -> None:
    item = question(GapCategory.TOOL)
    mismatch = process_coach_answer(item, CoachAnswer(question_id="different", answer_text="SAP"))
    blank = process_coach_answer(item, CoachAnswer(question_id=item.question_id, answer_text="  "))
    negative = process_coach_answer(item, CoachAnswer(question_id=item.question_id, answer_text="Hayır"))
    generic = process_coach_answer(item, CoachAnswer(question_id=item.question_id, answer_text="Evet"))

    assert mismatch.issue_codes == ("question_id_mismatch",)
    assert blank.issue_codes == ("invalid_answer",)
    assert negative.status is CoachAnswerStatus.ANSWERED_NO and negative.candidate is None
    assert generic.issue_codes == ("insufficient_answer_detail",) and generic.candidate is None


def test_explicit_tools_preserve_exact_user_wording_without_strengthening() -> None:
    for answer_text, expected in (("SAP", "SAP"), ("Excel", "Excel"), ("Advanced Excel", "Advanced Excel"), ("Siemens TIA Portal", "Siemens TIA Portal")):
        _, _, result = process(GapCategory.TOOL, answer_text)
        assert result.status is CoachAnswerStatus.CANDIDATE_CREATED
        assert result.candidate is not None and result.candidate.proposed_statement == expected


def test_certification_and_explicit_english_language_create_compatible_candidates() -> None:
    _, _, certification = process(GapCategory.CERTIFICATION, "PMP")
    _, _, language = process(GapCategory.LANGUAGE, "English - B2")

    assert certification.candidate is not None and certification.candidate.candidate_type.value == "certification"
    assert language.candidate is not None and language.candidate.candidate_type.value == "language"


def test_unsupported_turkish_language_and_metric_answers_are_deferred_without_rewriting() -> None:
    _, _, language = process(GapCategory.LANGUAGE, "İngilizce ileri seviye, Almanca başlangıç")
    _, _, metric = process(GapCategory.METRIC, "Reduced cycle time by 12%")
    _, _, metric_without_number = process(GapCategory.METRIC, "Improved cycle time")

    assert language.issue_codes == ("unsupported_answer_mapping",)
    assert language.normalized_answer == "İngilizce ileri seviye, Almanca başlangıç"
    assert metric.issue_codes == ("unsupported_answer_mapping",)
    assert metric.normalized_answer == "Reduced cycle time by 12%"
    assert metric_without_number.candidate is None


def test_leadership_and_category_mismatch_do_not_invent_responsibilities() -> None:
    _, _, leadership = process(GapCategory.LEADERSHIP, "Managed 6 technicians")
    _, _, mismatch = process(GapCategory.CERTIFICATION, "I use SAP")

    assert leadership.candidate is None and leadership.issue_codes == ("unsupported_answer_mapping",)
    assert mismatch.candidate is None and mismatch.issue_codes == ("category_answer_mismatch",)


def test_candidate_keeps_user_answer_provenance_and_always_requires_confirmation() -> None:
    item, _, result = process(GapCategory.TOOL, "SAP", question_id="tool-question", refs=())

    assert result.candidate is not None
    assert result.source is not None and result.source.source_type is SourceType.USER_INPUT
    assert result.source.reference == "coach_question:tool-question"
    assert result.source.original_text == "SAP"
    assert result.candidate.evidence_references == ()
    assert result.candidate.source == result.source
    assert result.candidate.verification_status is VerificationStatus.INFERRED_UNVERIFIED
    assert result.candidate.requires_user_confirmation is True
    assert result.candidate.is_claim_usable is False
    assert item.question_id == "tool-question"


def test_same_input_is_deterministic_and_confirmation_remains_explicit() -> None:
    item = question(GapCategory.TOOL)
    answer = CoachAnswer(question_id=item.question_id, answer_text="Python")
    first = process_coach_answer(item, answer)
    second = process_coach_answer(item, answer)

    assert first == second
    assert first.candidate is not None
    accepted = resolve_candidate(first.candidate, ConfirmationAction.ACCEPT)
    assert accepted.promoted_fact is not None
    assert accepted.promoted_fact.verification_status is VerificationStatus.USER_PROVIDED
    assert accepted.promoted_fact.source == first.source
    assert accepted.audit.evidence_references == ("page:1:block:1",)
    assert first.candidate.verification_status is VerificationStatus.INFERRED_UNVERIFIED


def test_answer_processing_has_no_ai_or_profile_assembly_dependency() -> None:
    source = inspect.getsource(answer_service)
    assert "app.ai.providers" not in source
    assert "career_profile_assembly" not in source

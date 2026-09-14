import re
import unicodedata

from app.ai.career import AIConfidence, CandidateType, CareerFactCandidate
from app.domain.career import FactSource, SourceType
from app.services.career_gap_analysis import CoachQuestion, GapCategory
from app.services.coach_answer_processing.schemas import (
    CoachAnswer,
    CoachAnswerProcessingResult,
    CoachAnswerStatus,
)

_NEGATIVE_ANSWERS = {"no", "none", "hayır", "hayir"}
_LOW_INFORMATION_ANSWERS = {"yes", "evet", "maybe", "not sure", "bilmiyorum"}
_NAMED_VALUE_PATTERN = re.compile(r"^[^\n,;.!?]{1,80}$")
_LANGUAGE_PATTERN = re.compile(r"^(?P<language>[A-Za-z][A-Za-z ]{1,39})\s+-\s+(?P<proficiency>[A-Za-z0-9][A-Za-z0-9 .-]{0,39})$")
_NON_VALUE_PREFIXES = ("i use ", "i used ", "i have ")


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def _answer_source(question: CoachQuestion, answer: str) -> FactSource:
    return FactSource(
        source_type=SourceType.USER_INPUT,
        reference=f"coach_question:{question.question_id}",
        original_text=answer,
    )


def _candidate_references(question: CoachQuestion) -> tuple[str, ...]:
    return question.evidence_references


def _candidate(question: CoachQuestion, answer: str, candidate_type: CandidateType) -> CareerFactCandidate:
    return CareerFactCandidate(
        candidate_type=candidate_type,
        proposed_statement=answer,
        evidence_references=_candidate_references(question),
        source=_answer_source(question, answer),
        confidence=AIConfidence.HIGH,
        rationale=f"Explicit user answer to coach question {question.question_id}.",
    )


def _result(
    question: CoachQuestion,
    status: CoachAnswerStatus,
    *,
    answer: str | None = None,
    candidate: CareerFactCandidate | None = None,
    issue_codes: tuple[str, ...] = (),
) -> CoachAnswerProcessingResult:
    return CoachAnswerProcessingResult(
        source_question_id=question.question_id,
        status=status,
        candidate=candidate,
        source=_answer_source(question, answer) if answer is not None else None,
        normalized_answer=answer,
        issue_codes=issue_codes,
    )


def _is_explicit_named_value(answer: str) -> bool:
    return _NAMED_VALUE_PATTERN.fullmatch(answer) is not None and not answer.casefold().startswith(_NON_VALUE_PREFIXES)


def process_coach_answer(
    question: CoachQuestion,
    answer: CoachAnswer,
) -> CoachAnswerProcessingResult:
    """Create only an unverified candidate from a category-compatible explicit answer."""

    if answer.question_id != question.question_id:
        return _result(question, CoachAnswerStatus.REJECTED, issue_codes=("question_id_mismatch",))
    normalized_answer = _normalized(answer.answer_text)
    answer_key = normalized_answer.casefold()
    if not normalized_answer:
        return _result(question, CoachAnswerStatus.REJECTED, issue_codes=("invalid_answer",))
    if answer_key in _NEGATIVE_ANSWERS:
        return _result(question, CoachAnswerStatus.ANSWERED_NO, answer=normalized_answer)
    if answer_key in _LOW_INFORMATION_ANSWERS:
        return _result(
            question,
            CoachAnswerStatus.DEFERRED,
            answer=normalized_answer,
            issue_codes=("insufficient_answer_detail",),
        )

    if question.category is GapCategory.TOOL:
        if not _is_explicit_named_value(normalized_answer):
            return _result(question, CoachAnswerStatus.DEFERRED, answer=normalized_answer, issue_codes=("insufficient_answer_detail",))
        candidate = _candidate(question, normalized_answer, CandidateType.SKILL)
        return _result(question, CoachAnswerStatus.CANDIDATE_CREATED, answer=normalized_answer, candidate=candidate)
    if question.category is GapCategory.CERTIFICATION:
        if not _is_explicit_named_value(normalized_answer):
            return _result(question, CoachAnswerStatus.REJECTED, answer=normalized_answer, issue_codes=("category_answer_mismatch",))
        candidate = _candidate(question, normalized_answer, CandidateType.CERTIFICATION)
        return _result(question, CoachAnswerStatus.CANDIDATE_CREATED, answer=normalized_answer, candidate=candidate)
    if question.category is GapCategory.LANGUAGE:
        if _LANGUAGE_PATTERN.fullmatch(normalized_answer) is None:
            return _result(question, CoachAnswerStatus.DEFERRED, answer=normalized_answer, issue_codes=("unsupported_answer_mapping",))
        candidate = _candidate(question, normalized_answer, CandidateType.LANGUAGE)
        return _result(question, CoachAnswerStatus.CANDIDATE_CREATED, answer=normalized_answer, candidate=candidate)
    return _result(question, CoachAnswerStatus.DEFERRED, answer=normalized_answer, issue_codes=("unsupported_answer_mapping",))

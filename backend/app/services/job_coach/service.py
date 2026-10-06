import hashlib
import json
import re

from app.domain.job import JobProfile, JobRequirement, RequirementCategory, RequirementImportance
from app.services.career_gap_analysis import CoachQuestion, GapCategory, GapPriority
from app.services.career_gap_analysis.schemas import AnswerType
from app.services.job_coach.schemas import (
    JobCoachContext,
    JobCoachQuestion,
    JobCoachResult,
    JobCoachSkippedRequirement,
)
from app.services.job_match import JobMatchResult, RequirementMatchResult, RequirementMatchStatus

_PRIORITY_ORDER = {GapPriority.HIGH: 0, GapPriority.MEDIUM: 1, GapPriority.LOW: 2}
_SUPPORTED_NOT_EVIDENCED = {
    RequirementCategory.SKILL,
    RequirementCategory.TOOL,
    RequirementCategory.LANGUAGE,
    RequirementCategory.CERTIFICATION,
    RequirementCategory.OTHER,
    RequirementCategory.EXPERIENCE,
}
_CATEGORY_MAP = {
    RequirementCategory.SKILL: GapCategory.SKILL,
    RequirementCategory.TOOL: GapCategory.TOOL,
    RequirementCategory.LANGUAGE: GapCategory.LANGUAGE,
    RequirementCategory.CERTIFICATION: GapCategory.CERTIFICATION,
    RequirementCategory.OTHER: GapCategory.SKILL,
    RequirementCategory.EXPERIENCE: GapCategory.SKILL,
}
_TARGET_SECTION = {
    RequirementCategory.SKILL: "skills",
    RequirementCategory.TOOL: "skills",
    RequirementCategory.LANGUAGE: "languages",
    RequirementCategory.CERTIFICATION: "certifications",
    RequirementCategory.OTHER: "additional_facts",
    RequirementCategory.EXPERIENCE: "experience",
}
_LANGUAGE_PREFIX = re.compile(r"^(?P<language>[A-Za-z]+)\s+.+$")


def _priority(importance: RequirementImportance) -> GapPriority:
    return GapPriority.HIGH if importance is RequirementImportance.REQUIRED else GapPriority.MEDIUM


def _question_id(requirement: JobRequirement, category: GapCategory, purpose: str, status: RequirementMatchStatus) -> str:
    payload = json.dumps(
        {
            "requirement_id": requirement.requirement_id,
            "category": category.value,
            "purpose": purpose,
            "match_status": status.value,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _question_text(requirement: JobRequirement, status: RequirementMatchStatus) -> tuple[str, str] | None:
    if status is RequirementMatchStatus.PARTIAL:
        match = _LANGUAGE_PREFIX.fullmatch(requirement.text.strip())
        if match is None:
            return None
        language = match.group("language")
        return (
            f"The current profile includes {language}, but no verified proficiency level is recorded. What proficiency level would you personally state for {language}?",
            "language_proficiency_clarification",
        )
    if requirement.category is RequirementCategory.SKILL:
        return (
            f"Have you used or demonstrated {requirement.text} in your work, projects, or other professional experience? If yes, describe it accurately.",
            "missing_skill_evidence",
        )
    if requirement.category is RequirementCategory.TOOL:
        return (
            f"Have you used {requirement.text} in any role or project? If yes, enter the tool or system name as you actually used it.",
            "missing_tool_evidence",
        )
    if requirement.category is RequirementCategory.LANGUAGE:
        return (
            f"Do you have any proficiency in {requirement.text}? If yes, state the language and your actual proficiency level.",
            "missing_language_evidence",
        )
    if requirement.category is RequirementCategory.CERTIFICATION:
        return (
            f"Do you hold {requirement.text} or another relevant certification? If yes, enter the certification name exactly.",
            "missing_certification_evidence",
        )
    if requirement.category in {RequirementCategory.OTHER, RequirementCategory.EXPERIENCE}:
        return (
            f"Do you have explicit experience or eligibility evidence for: {requirement.text}? If yes, describe only the factual detail you would include in your CV.",
            "missing_job_requirement_evidence",
        )
    return None


def _skipped(requirement: JobRequirement, status: RequirementMatchStatus | None, reason_code: str) -> JobCoachSkippedRequirement:
    return JobCoachSkippedRequirement(
        requirement_id=requirement.requirement_id,
        requirement_text=requirement.text,
        category=requirement.category,
        importance=requirement.importance,
        match_status=status,
        reason_code=reason_code,
        job_source_references=requirement.source_references,
    )


def _make_question(requirement: JobRequirement, status: RequirementMatchStatus) -> JobCoachQuestion | None:
    text_and_purpose = _question_text(requirement, status)
    category = _CATEGORY_MAP.get(requirement.category)
    if text_and_purpose is None or category is None:
        return None
    question_text, purpose = text_and_purpose
    question = CoachQuestion(
        question_id=_question_id(requirement, category, purpose, status),
        category=category,
        question_text=question_text,
        reason=f"The job listing includes {requirement.text}, but the current trusted profile does not contain sufficient evidence for this requirement.",
        target_section=_TARGET_SECTION[requirement.category],
        priority=_priority(requirement.importance),
        evidence_references=(),
        missing_signal=requirement.requirement_id,
        answer_type=AnswerType.FREE_TEXT if requirement.category is RequirementCategory.LANGUAGE else AnswerType.YES_NO_DETAILS,
        question_type=purpose,
        related_requirement_id=requirement.requirement_id,
        expected_information="Only an accurate first-person detail; no inferred job requirement is accepted.",
        potential_impact=f"May strengthen the { _TARGET_SECTION[requirement.category] } section after confirmation.",
    )
    return JobCoachQuestion(
        question=question,
        requirement_id=requirement.requirement_id,
        requirement_text=requirement.text,
        requirement_category=requirement.category,
        importance=requirement.importance,
        match_status=status,
        job_source_references=requirement.source_references,
    )


def generate_job_specific_coach_questions(
    job_profile: JobProfile,
    match_result: JobMatchResult,
    *,
    context: JobCoachContext | None = None,
) -> JobCoachResult:
    """Create bounded, neutral questions from existing match classifications only."""

    active_context = context or JobCoachContext()
    match_by_id: dict[str, RequirementMatchResult] = {}
    skipped: list[JobCoachSkippedRequirement] = []
    profile_ids = {requirement.requirement_id for requirement in job_profile.requirements}
    for result in match_result.requirement_results:
        requirement_id = result.requirement.requirement_id
        if requirement_id not in profile_ids:
            skipped.append(_skipped(result.requirement, result.status, "dangling_match_requirement"))
        elif requirement_id not in match_by_id:
            match_by_id[requirement_id] = result

    candidates: list[tuple[int, int, str, JobCoachQuestion]] = []
    processed_ids: set[str] = set()
    for index, requirement in enumerate(job_profile.requirements):
        if requirement.requirement_id in processed_ids:
            continue
        processed_ids.add(requirement.requirement_id)
        match = match_by_id.get(requirement.requirement_id)
        if match is None:
            skipped.append(_skipped(requirement, None, "missing_match_result"))
            continue
        status = match.status
        eligible = status is RequirementMatchStatus.NOT_EVIDENCED and requirement.category in _SUPPORTED_NOT_EVIDENCED
        eligible = eligible or (status is RequirementMatchStatus.PARTIAL and requirement.category is RequirementCategory.LANGUAGE)
        if eligible:
            question = _make_question(requirement, status)
            if question is not None:
                candidates.append((_PRIORITY_ORDER[question.question.priority], index, question.question.question_id, question))
                continue
            skipped.append(_skipped(requirement, status, "unsupported_partial_structure"))
        elif status is RequirementMatchStatus.NOT_EVALUABLE:
            skipped.append(_skipped(requirement, status, "not_evaluable_requirement"))
        elif status is RequirementMatchStatus.PARTIAL:
            skipped.append(_skipped(requirement, status, "unsupported_partial_category"))
        elif status is RequirementMatchStatus.NOT_EVIDENCED:
            skipped.append(_skipped(requirement, status, "unsupported_category"))

    ordered = sorted(candidates, key=lambda item: (item[0], item[1], item[2]))
    selected = tuple(item[3] for item in ordered[: active_context.max_questions])
    return JobCoachResult(
        questions=selected,
        skipped_requirements=tuple(skipped),
        eligible_count=len(ordered),
        generated_count=len(selected),
        truncated_count=max(0, len(ordered) - len(selected)),
    )

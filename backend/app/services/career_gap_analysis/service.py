import hashlib
import json
import unicodedata

from app.domain.career import CareerFact, CareerProfile, VerificationStatus, WorkExperience
from app.services.career_gap_analysis.schemas import (
    AnswerType,
    CoachQuestion,
    GapAnalysisContext,
    GapAnalysisResult,
    GapCategory,
    GapPriority,
    SkippedOpportunity,
)

_TRUSTED_STATUSES = {VerificationStatus.VERIFIED, VerificationStatus.USER_PROVIDED}
_PRIORITY_ORDER = {GapPriority.HIGH: 0, GapPriority.MEDIUM: 1, GapPriority.LOW: 2}
_LEADERSHIP_TERMS = {"lead", "manager", "supervisor", "director", "principal", "head"}
_PROJECT_TERMS = {"project", "program", "manager", "lead"}
_INTERNSHIP_TERMS = {"intern", "stajyer", "trainee", "apprentice"}


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _trusted(fact: CareerFact) -> bool:
    return fact.verification_status in _TRUSTED_STATUSES


def _references(facts: tuple[CareerFact, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            fact.source.reference
            for fact in facts
            if _trusted(fact) and fact.source.reference is not None
        )
    )


def _question_id(
    category: GapCategory,
    target_section: str,
    missing_signal: str,
    related_role: str | None,
    evidence_references: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "category": category.value,
            "target_section": target_section,
            "missing_signal": missing_signal,
            "related_role": related_role,
            "evidence_references": evidence_references,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_question(
    *,
    category: GapCategory,
    question_text: str,
    reason: str,
    target_section: str,
    priority: GapPriority,
    missing_signal: str,
    answer_type: AnswerType,
    related_role: str | None = None,
    evidence_references: tuple[str, ...] = (),
) -> CoachQuestion:
    return CoachQuestion(
        question_id=_question_id(category, target_section, missing_signal, related_role, evidence_references),
        category=category,
        question_text=question_text,
        reason=reason,
        target_section=target_section,
        priority=priority,
        evidence_references=evidence_references,
        missing_signal=missing_signal,
        answer_type=answer_type,
        related_role=related_role,
    )


def _role_terms(experience: WorkExperience, context: GapAnalysisContext) -> set[str]:
    values = [experience.title, context.target_role or "", context.career_direction or ""]
    values.extend(context.target_job_keywords)
    return set(" ".join(values).casefold().replace("/", " ").replace("-", " ").split())


def _role_priority(experience: WorkExperience, context: GapAnalysisContext) -> tuple[int, int, int, str]:
    """Current and recent substantive roles come first; an open range is not current."""
    terms = _role_terms(experience, context)
    internship = bool(terms & _INTERNSHIP_TERMS)
    end = experience.end_date or experience.start_date
    year = end.year
    month = getattr(end, "month", None) or 1
    impact = any(_trusted(fact) and (fact.metrics or fact.tools or fact.skills) for fact in experience.facts)
    return (0 if experience.is_current else 1, 1 if internship else 0, -year * 12 - month - (1 if impact else 0), _normalized(experience.title))


def _experience_questions(
    experience: WorkExperience,
    context: GapAnalysisContext,
) -> tuple[list[CoachQuestion], list[SkippedOpportunity]]:
    facts = experience.facts
    trusted_facts = tuple(fact for fact in facts if _trusted(fact))
    references = _references(trusted_facts)
    questions: list[CoachQuestion] = []
    skipped: list[SkippedOpportunity] = []
    role = experience.title

    if not any(fact.metrics for fact in trusted_facts):
        questions.append(
            _make_question(
                category=GapCategory.METRIC,
                question_text=(
                    f"For your {role} role, can any responsibility be supported by a measurable result "
                    "such as cycle-time, quality, throughput, cost, or downtime improvement?"
                ),
                reason="No measurable achievement evidence is currently stated for this role.",
                target_section="experience",
                priority=GapPriority.HIGH,
                missing_signal="no_trusted_metric_evidence",
                answer_type=AnswerType.YES_NO_DETAILS,
                related_role=role,
                evidence_references=references,
            )
        )
    if not any(fact.skills or fact.tools for fact in trusted_facts):
        questions.append(
            _make_question(
                category=GapCategory.TOOL,
                question_text=f"In your {role} role, which tools, systems, or technical platforms did you use that are not currently evidenced?",
                reason="No explicit tool or technical-skill evidence is currently stated for this role.",
                target_section="experience",
                priority=GapPriority.MEDIUM,
                missing_signal="no_trusted_tool_evidence",
                answer_type=AnswerType.YES_NO_DETAILS,
                related_role=role,
                evidence_references=references,
            )
        )

    terms = _role_terms(experience, context)
    if terms & _LEADERSHIP_TERMS:
        if not any("lead" in fact.statement.casefold() or "manag" in fact.statement.casefold() for fact in trusted_facts):
            questions.append(
                _make_question(
                    category=GapCategory.LEADERSHIP,
                    question_text=f"In your {role} role, did you formally lead or coordinate technicians, operators, or engineers?",
                    reason="The role or supplied context makes leadership evidence relevant, but it is not currently stated.",
                    target_section="experience",
                    priority=GapPriority.MEDIUM,
                    missing_signal="no_trusted_leadership_evidence",
                    answer_type=AnswerType.YES_NO_DETAILS,
                    related_role=role,
                    evidence_references=references,
                )
            )
    else:
        skipped.append(SkippedOpportunity(category=GapCategory.LEADERSHIP, reason_code="insufficient_role_context"))

    if terms & _PROJECT_TERMS:
        questions.append(
            _make_question(
                category=GapCategory.PROJECT_MANAGEMENT,
                question_text=f"In your {role} role, did you plan, coordinate, or deliver a project that is not currently evidenced?",
                reason="The role or supplied context makes project-management evidence relevant, but it is not currently stated.",
                target_section="projects",
                priority=GapPriority.LOW,
                missing_signal="no_trusted_project_management_evidence",
                answer_type=AnswerType.YES_NO_DETAILS,
                related_role=role,
                evidence_references=references,
            )
        )
    else:
        skipped.append(SkippedOpportunity(category=GapCategory.PROJECT_MANAGEMENT, reason_code="insufficient_role_context"))
    return questions, skipped


def analyze_career_profile_gaps(
    profile: CareerProfile,
    context: GapAnalysisContext | None = None,
) -> GapAnalysisResult:
    """Generate bounded questions about missing trusted evidence without creating facts."""

    active_context = context or GapAnalysisContext()
    questions: list[CoachQuestion] = []
    skipped: list[SkippedOpportunity] = []
    if not profile.certifications:
        questions.append(
            _make_question(
                category=GapCategory.CERTIFICATION,
                question_text="Do you hold any professional certifications that are not currently listed?",
                reason="No certifications are currently listed in the trusted profile.",
                target_section="certifications",
                priority=GapPriority.LOW,
                missing_signal="no_certifications",
                answer_type=AnswerType.YES_NO_DETAILS,
            )
        )
    if not profile.languages:
        questions.append(
            _make_question(
                category=GapCategory.LANGUAGE,
                question_text="Are there languages and explicit proficiency levels that are not currently listed?",
                reason="No languages are currently listed in the trusted profile.",
                target_section="languages",
                priority=GapPriority.LOW,
                missing_signal="no_languages",
                answer_type=AnswerType.FREE_TEXT,
            )
        )
    for experience in sorted(profile.work_experiences, key=lambda item: _role_priority(item, active_context)):
        experience_questions, experience_skipped = _experience_questions(experience, active_context)
        questions.extend(experience_questions)
        skipped.extend(experience_skipped)

    unique_questions = {question.question_id: question for question in questions}
    ordered_questions = sorted(
        unique_questions.values(),
        key=lambda question: (
            _PRIORITY_ORDER[question.priority],
            _role_priority(next((role for role in profile.work_experiences if role.title == question.related_role), profile.work_experiences[0]), active_context) if question.related_role and profile.work_experiences else (9, 9, 9, ""),
            question.category.value,
            question.question_id,
        ),
    )
    # An initial coach batch should be actionable, not four near-identical metric prompts.
    selected: list[CoachQuestion] = []
    category_limits = {GapCategory.METRIC: 1, GapCategory.TOOL: 2}
    category_counts: dict[GapCategory, int] = {}
    for question in ordered_questions:
        if category_counts.get(question.category, 0) >= category_limits.get(question.category, active_context.max_questions):
            continue
        selected.append(question)
        category_counts[question.category] = category_counts.get(question.category, 0) + 1
        if len(selected) == active_context.max_questions:
            break
    return GapAnalysisResult(
        questions=tuple(selected),
        skipped_opportunities=tuple(sorted(skipped, key=lambda item: (item.category.value, item.reason_code))),
        total_recommendations=len(ordered_questions),
        more_recommendations_available=len(ordered_questions) > len(selected),
    )

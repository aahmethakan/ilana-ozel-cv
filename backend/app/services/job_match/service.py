import unicodedata
from collections.abc import Iterable

from app.domain.career import CareerProfile, SourceType, VerificationStatus
from app.domain.job import JobProfile, JobRequirement, RequirementCategory, RequirementImportance
from app.services.job_analysis import UnresolvedJobItem
from app.services.job_match.schemas import (
    JobMatchResult,
    RequirementMatchResult,
    RequirementMatchStatus,
)

_TRUSTED_VERIFICATION_STATUSES = {
    VerificationStatus.VERIFIED,
    VerificationStatus.USER_PROVIDED,
}
_TRUSTED_SOURCE_TYPES = {SourceType.MASTER_CV, SourceType.USER_INPUT}

_MATCHED_EXPLANATION = "Explicit trusted profile evidence supports this requirement."
_PARTIAL_EXPLANATION = "Related explicit evidence exists, but the full requirement is not evidenced."
_NOT_EVIDENCED_EXPLANATION = "No sufficient evidence for this requirement was found in the current trusted career profile."
_NOT_EVALUABLE_EXPLANATION = "This requirement cannot be evaluated safely by the deterministic matcher."


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().casefold().split())


def _result(
    requirement: JobRequirement,
    status: RequirementMatchStatus,
    reason_code: str,
    evidence_references: Iterable[str] = (),
    explanation: str | None = None,
) -> RequirementMatchResult:
    explanations = {
        RequirementMatchStatus.MATCHED: _MATCHED_EXPLANATION,
        RequirementMatchStatus.PARTIAL: _PARTIAL_EXPLANATION,
        RequirementMatchStatus.NOT_EVIDENCED: _NOT_EVIDENCED_EXPLANATION,
        RequirementMatchStatus.NOT_EVALUABLE: _NOT_EVALUABLE_EXPLANATION,
    }
    return RequirementMatchResult(
        requirement=requirement,
        status=status,
        matched_evidence_references=tuple(dict.fromkeys(evidence_references)),
        reason_code=reason_code,
        explanation=explanation or explanations[status],
    )


def _trusted_named_references(profile: CareerProfile, requirement_text: str, category: RequirementCategory) -> tuple[str, ...]:
    target = _normalized(requirement_text)
    facts = profile.skills if category is RequirementCategory.SKILL else profile.tools
    return tuple(
        fact.source.reference
        for fact in facts
        if fact.verification_status in _TRUSTED_VERIFICATION_STATUSES
        and fact.source.reference is not None
        and any(_normalized(value) == target for value in (fact.skills if category is RequirementCategory.SKILL else fact.tools))
    )


def _has_unreferenced_trusted_named_evidence(profile: CareerProfile, requirement_text: str, category: RequirementCategory) -> bool:
    target = _normalized(requirement_text)
    facts = profile.skills if category is RequirementCategory.SKILL else profile.tools
    return any(
        fact.verification_status in _TRUSTED_VERIFICATION_STATUSES
        and fact.source.reference is None
        and any(_normalized(value) == target for value in (fact.skills if category is RequirementCategory.SKILL else fact.tools))
        for fact in facts
    )


def _match_skill_or_tool(requirement: JobRequirement, profile: CareerProfile) -> RequirementMatchResult:
    references = _trusted_named_references(profile, requirement.text, requirement.category)
    if references:
        return _result(requirement, RequirementMatchStatus.MATCHED, "exact_trusted_skill_match", references)
    if _has_unreferenced_trusted_named_evidence(profile, requirement.text, requirement.category):
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "trusted_evidence_missing_reference")
    return _result(requirement, RequirementMatchStatus.NOT_EVIDENCED, "no_exact_trusted_skill_evidence")


def _language_parts(text: str, profile: CareerProfile) -> tuple[str, str | None] | None:
    normalized_text = _normalized(text)
    for item in profile.languages:
        language = _normalized(item.language)
        if normalized_text == language:
            return language, None
        prefix = f"{language} "
        if normalized_text.startswith(prefix):
            return language, normalized_text[len(prefix):]
    return None


def _match_language(requirement: JobRequirement, profile: CareerProfile) -> RequirementMatchResult:
    parsed = _language_parts(requirement.text, profile)
    if parsed is None:
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "unsupported_language_requirement_structure")
    language, required_proficiency = parsed
    trusted = [
        item for item in profile.languages
        if item.source.source_type in _TRUSTED_SOURCE_TYPES and _normalized(item.language) == language
    ]
    referenced = [item for item in trusted if item.source.reference is not None]
    if not trusted:
        return _result(requirement, RequirementMatchStatus.NOT_EVIDENCED, "no_exact_trusted_language_evidence")
    if not referenced:
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "trusted_evidence_missing_reference")
    references = tuple(item.source.reference for item in referenced if item.source.reference is not None)
    if required_proficiency is None:
        return _result(requirement, RequirementMatchStatus.MATCHED, "exact_trusted_language_match", references)
    if any(_normalized(item.proficiency or "") == required_proficiency for item in referenced):
        return _result(requirement, RequirementMatchStatus.MATCHED, "exact_trusted_language_and_proficiency_match", references)
    return _result(
        requirement,
        RequirementMatchStatus.PARTIAL,
        "language_identity_matched_proficiency_not_evidenced",
        references,
        "Explicit language identity is evidenced, but the required proficiency is not evidenced.",
    )


def _match_certification(requirement: JobRequirement, profile: CareerProfile) -> RequirementMatchResult:
    target = _normalized(requirement.text)
    trusted = [
        item for item in profile.certifications
        if item.source.source_type in _TRUSTED_SOURCE_TYPES and _normalized(item.name) == target
    ]
    referenced = [item for item in trusted if item.source.reference is not None]
    if not trusted:
        return _result(requirement, RequirementMatchStatus.NOT_EVIDENCED, "no_exact_trusted_certification_evidence")
    if not referenced:
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "trusted_evidence_missing_reference")
    return _result(
        requirement,
        RequirementMatchStatus.MATCHED,
        "exact_trusted_certification_match",
        (item.source.reference for item in referenced if item.source.reference is not None),
    )


def _match_requirement(requirement: JobRequirement, profile: CareerProfile) -> RequirementMatchResult:
    if requirement.category in {RequirementCategory.SKILL, RequirementCategory.TOOL}:
        return _match_skill_or_tool(requirement, profile)
    if requirement.category is RequirementCategory.LANGUAGE:
        return _match_language(requirement, profile)
    if requirement.category is RequirementCategory.CERTIFICATION:
        return _match_certification(requirement, profile)
    if requirement.category is RequirementCategory.EDUCATION:
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "education_structure_not_safely_comparable")
    if requirement.category is RequirementCategory.EXPERIENCE:
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "experience_structure_not_safely_comparable")
    return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "unsupported_requirement_category")


def _unique_requirements(requirements: tuple[JobRequirement, ...]) -> tuple[JobRequirement, ...]:
    unique_by_key: dict[tuple[RequirementCategory, str], JobRequirement] = {}
    for requirement in requirements:
        key = (requirement.category, _normalized(requirement.text))
        existing = unique_by_key.get(key)
        if existing is None:
            unique_by_key[key] = requirement
            continue
        unique_by_key[key] = existing.model_copy(update={
            "importance": existing.importance if existing.importance is requirement.importance else RequirementImportance.UNKNOWN,
            "source_references": tuple(dict.fromkeys(existing.source_references + requirement.source_references)),
            "source_texts": tuple(dict.fromkeys(existing.source_texts + requirement.source_texts)),
        })
    return tuple(unique_by_key.values())


def match_job_to_profile(job_profile: JobProfile, career_profile: CareerProfile, unresolved_job_items: tuple[UnresolvedJobItem, ...] = ()) -> JobMatchResult:
    """Compare explicit job requirements with trusted profile evidence only."""

    results = tuple(_match_requirement(requirement, career_profile) for requirement in _unique_requirements(job_profile.requirements))
    return JobMatchResult(
        requirement_results=results,
        matched_required_count=sum(item.status is RequirementMatchStatus.MATCHED and item.requirement.importance is RequirementImportance.REQUIRED for item in results),
        matched_preferred_count=sum(item.status is RequirementMatchStatus.MATCHED and item.requirement.importance is RequirementImportance.PREFERRED for item in results),
        not_evidenced_required_count=sum(item.status is RequirementMatchStatus.NOT_EVIDENCED and item.requirement.importance is RequirementImportance.REQUIRED for item in results),
        not_evidenced_preferred_count=sum(item.status is RequirementMatchStatus.NOT_EVIDENCED and item.requirement.importance is RequirementImportance.PREFERRED for item in results),
        partial_count=sum(item.status is RequirementMatchStatus.PARTIAL for item in results),
        not_evaluable_count=sum(item.status is RequirementMatchStatus.NOT_EVALUABLE for item in results),
        unresolved_job_items=unresolved_job_items,
    )

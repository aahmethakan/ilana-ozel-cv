from collections.abc import Iterable

from app.domain.career import CareerProfile, SourceType, VerificationStatus
from app.domain.job import JobProfile, JobRequirement, RequirementCategory, RequirementImportance
from app.services.job_analysis import UnresolvedJobItem
from app.services.job_match.schemas import (
    JobMatchResult,
    RequirementMatchResult,
    RequirementMatchStatus,
    RequirementMatchType,
)
from app.services.job_match.semantic import is_conservative_partial, is_controlled_synonym, normalize_text

_TRUSTED_VERIFICATION_STATUSES = {
    VerificationStatus.VERIFIED,
    VerificationStatus.USER_PROVIDED,
}
_TRUSTED_SOURCE_TYPES = {SourceType.MASTER_CV, SourceType.USER_INPUT}

_MATCHED_EXPLANATION = "Explicit trusted profile evidence supports this requirement."
_PARTIAL_EXPLANATION = "Related explicit evidence exists, but the full requirement is not evidenced."
_NOT_EVIDENCED_EXPLANATION = "No sufficient evidence for this requirement was found in the current trusted career profile."
_NOT_EVALUABLE_EXPLANATION = "This requirement cannot be evaluated safely by the deterministic matcher."


def _trusted(fact) -> bool:
    return fact.verification_status in _TRUSTED_VERIFICATION_STATUSES and fact.source.source_type in _TRUSTED_SOURCE_TYPES


def _normalized(value: str) -> str:
    return normalize_text(value)


def _result(
    requirement: JobRequirement,
    status: RequirementMatchStatus,
    reason_code: str,
    evidence_references: Iterable[str] = (),
    explanation: str | None = None,
    match_type: RequirementMatchType | None = None,
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
        match_type=match_type or (
            RequirementMatchType.PARTIAL if status is RequirementMatchStatus.PARTIAL
            else RequirementMatchType.UNMATCHED if status in {RequirementMatchStatus.NOT_EVIDENCED, RequirementMatchStatus.NOT_EVALUABLE}
            else RequirementMatchType.EXACT
        ),
        confidence="high" if status is RequirementMatchStatus.MATCHED else "medium" if status is RequirementMatchStatus.PARTIAL else "none",
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
        facts = profile.skills if requirement.category is RequirementCategory.SKILL else profile.tools
        values = [value for fact in facts if _trusted(fact) for value in (fact.skills if requirement.category is RequirementCategory.SKILL else fact.tools)]
        exact = any(value.strip() == requirement.text.strip() for value in values)
        return _result(
            requirement,
            RequirementMatchStatus.MATCHED,
            "exact_trusted_skill_match" if exact else "normalized_exact_trusted_skill_match",
            references,
            match_type=RequirementMatchType.EXACT if exact else RequirementMatchType.NORMALIZED_EXACT,
        )
    if _has_unreferenced_trusted_named_evidence(profile, requirement.text, requirement.category):
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "trusted_evidence_missing_reference")
    facts = profile.skills if requirement.category is RequirementCategory.SKILL else profile.tools
    candidates = [
        (value, fact.source.reference)
        for fact in facts if _trusted(fact) and fact.source.reference
        for value in (fact.skills if requirement.category is RequirementCategory.SKILL else fact.tools)
    ]
    for value, reference in candidates:
        if is_controlled_synonym(value, requirement.text):
            return _result(requirement, RequirementMatchStatus.MATCHED, "controlled_synonym", (reference,), match_type=RequirementMatchType.CONTROLLED_SEMANTIC)
    # Tool/technology names never receive fuzzy expansion.  Skills may receive a
    # literal subset result only, which does not create a candidate fact.
    if requirement.category is RequirementCategory.SKILL:
        for value, reference in candidates:
            if _normalized(value) not in {"sap", "plc", "python"} and is_conservative_partial(value, requirement.text):
                return _result(requirement, RequirementMatchStatus.PARTIAL, "candidate_skill_is_unqualified_subset", (reference,), match_type=RequirementMatchType.PARTIAL)
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
        suffix = f" {language}"
        if normalized_text.endswith(suffix) and normalized_text[:-len(suffix)] in {"advanced"}:
            return language, normalized_text[:-len(suffix)]
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
    if required_proficiency == "advanced" and any(_normalized(item.proficiency or "") == "c1" for item in referenced):
        return _result(requirement, RequirementMatchStatus.MATCHED, "controlled_language_proficiency", references, match_type=RequirementMatchType.CONTROLLED_SEMANTIC)
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
        certification_target = target.removesuffix(" certification").removesuffix(" certificate")
        trusted = [
            item for item in profile.certifications
            if item.source.source_type in _TRUSTED_SOURCE_TYPES
            and _normalized(item.name) == certification_target
        ]
        if trusted:
            referenced = [item for item in trusted if item.source.reference is not None]
            if not referenced:
                return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "trusted_evidence_missing_reference")
            return _result(requirement, RequirementMatchStatus.MATCHED, "controlled_certification_label", (item.source.reference for item in referenced if item.source.reference is not None), match_type=RequirementMatchType.CONTROLLED_SEMANTIC)
        return _result(requirement, RequirementMatchStatus.NOT_EVIDENCED, "no_exact_trusted_certification_evidence")
    if not referenced:
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "trusted_evidence_missing_reference")
    return _result(
        requirement,
        RequirementMatchStatus.MATCHED,
        "exact_trusted_certification_match",
        (item.source.reference for item in referenced if item.source.reference is not None),
    )


def _work_evidence(profile: CareerProfile) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for role in profile.work_experiences:
        for fact in role.facts:
            if _trusted(fact) and fact.source.reference:
                values.append((f"{role.title} {fact.statement}", fact.source.reference))
    return tuple(values)


def _match_education(requirement: JobRequirement, profile: CareerProfile) -> RequirementMatchResult:
    target = _normalized(requirement.text)
    if not any(term in target for term in ("degree", "bachelor", "master", "engineering", "physics")):
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "unsupported_education_requirement")
    evidence = [(f"{item.degree or ''} {item.field_of_study or ''}", tuple(f.source.reference for f in item.facts if _trusted(f) and f.source.reference)) for item in profile.education]
    if not evidence:
        return _result(requirement, RequirementMatchStatus.NOT_EVIDENCED, "no_trusted_education_evidence")
    refs = tuple(reference for _, references in evidence for reference in references)
    if "mechanical engineering" in target and any("mechanical engineering" in _normalized(value) for value, _ in evidence):
        return _result(requirement, RequirementMatchStatus.PARTIAL, "related_technical_degree", refs)
    if "related technical" in target and any("engineering" in _normalized(value) or "physics" in _normalized(value) for value, _ in evidence):
        return _result(requirement, RequirementMatchStatus.MATCHED, "related_technical_degree", refs)
    return _result(requirement, RequirementMatchStatus.NOT_EVIDENCED, "education_field_not_evidenced")


def _match_experience_or_other(requirement: JobRequirement, profile: CareerProfile) -> RequirementMatchResult:
    target = _normalized(requirement.text)
    if requirement.category is RequirementCategory.OTHER:
        # A generic requirements list does not safely establish whether a named
        # item is a skill or a tool.  It may nevertheless match an existing,
        # explicitly verified named fact by exact text only.  This never creates
        # a candidate fact and deliberately has no synonym or partial fallback.
        named_references = tuple(dict.fromkeys(
            _trusted_named_references(profile, requirement.text, RequirementCategory.SKILL)
            + _trusted_named_references(profile, requirement.text, RequirementCategory.TOOL)
        ))
        if named_references:
            return _result(requirement, RequirementMatchStatus.MATCHED, "exact_named_profile_evidence", named_references)
    evidence = _work_evidence(profile)
    concepts = {
        "troubleshoot": ("troubleshoot", "fault", "root cause", "diagnos"),
        "commission": ("commission", "installation", "mainten", "service", "support"),
        "drawing": ("drawing", "schematic", "documentation"),
        "measurement": ("measurement", "testing", "diagnostic", "calibrat"),
        "customer": ("customer", "client", "training", "support"),
        "english": (), "travel": (), "driving": (), "crm": ("crm", "ticketing"),
        "microscopy": ("microscopy", "sem", "fib-sem"), "vacuum": ("vacuum",), "high-voltage": ("high-voltage",),
    }
    key = next((name for name in concepts if name in target), None)
    if key in {"english", "travel", "driving"}:
        return _result(requirement, RequirementMatchStatus.NOT_EVIDENCED, f"{key}_not_explicitly_evidenced")
    if key is None:
        if requirement.category is RequirementCategory.EXPERIENCE and profile.work_experiences:
            refs = tuple(reference for _, reference in evidence)
            return _result(requirement, RequirementMatchStatus.PARTIAL, "work_history_related_but_role_not_proven", refs)
        return _result(requirement, RequirementMatchStatus.NOT_EVALUABLE, "unsupported_controlled_requirement")
    hits = tuple(reference for value, reference in evidence if any(term in _normalized(value) for term in concepts[key]))
    if hits:
        status = RequirementMatchStatus.MATCHED if key not in {"troubleshoot", "commission"} else RequirementMatchStatus.PARTIAL
        return _result(requirement, status, f"controlled_{key}_evidence", hits)
    return _result(requirement, RequirementMatchStatus.NOT_EVIDENCED, f"no_{key}_evidence")


def _match_requirement(requirement: JobRequirement, profile: CareerProfile) -> RequirementMatchResult:
    if requirement.category in {RequirementCategory.SKILL, RequirementCategory.TOOL}:
        return _match_skill_or_tool(requirement, profile)
    if requirement.category is RequirementCategory.LANGUAGE:
        return _match_language(requirement, profile)
    if requirement.category is RequirementCategory.CERTIFICATION:
        return _match_certification(requirement, profile)
    if requirement.category is RequirementCategory.EDUCATION:
        return _match_education(requirement, profile)
    if requirement.category in {RequirementCategory.EXPERIENCE, RequirementCategory.OTHER}:
        return _match_experience_or_other(requirement, profile)
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

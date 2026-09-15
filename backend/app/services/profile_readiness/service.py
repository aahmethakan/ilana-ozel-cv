from collections.abc import Iterable, Sequence

from app.domain.career import CareerFact, CareerProfile, FactSource, SourceType
from app.domain.document import CVDocument, SectionType
from app.extraction.career import UnresolvedEvidence
from app.services.profile_readiness.schemas import (
    CareerProfileReadinessFinding,
    CareerProfileReadinessResult,
    ReadinessFindingImpact,
    ReadinessStatus,
    TrustedProfileSummary,
)

_DIRECT_SOURCE_TYPES = {SourceType.MASTER_CV, SourceType.USER_INPUT}
_MEANINGFUL_UNRESOLVED_SECTIONS = {
    SectionType.SUMMARY,
    SectionType.SKILLS,
    SectionType.CERTIFICATIONS,
    SectionType.LANGUAGES,
    SectionType.PROJECTS,
    SectionType.PUBLICATIONS,
    SectionType.ADDITIONAL,
    SectionType.UNKNOWN,
}


def _is_directly_sourced(source: FactSource) -> bool:
    return source.source_type in _DIRECT_SOURCE_TYPES


def _trusted_facts_count(facts: Iterable[CareerFact]) -> int:
    return sum(fact.is_claim_usable for fact in facts)


def _has_trusted_fact(facts: Iterable[CareerFact]) -> bool:
    return any(fact.is_claim_usable for fact in facts)


def _references(items: Iterable[UnresolvedEvidence]) -> tuple[str, ...]:
    return tuple(sorted({item.block_reference for item in items}))


def _finding(
    code: str,
    impact: ReadinessFindingImpact,
    message: str,
    *,
    references: tuple[str, ...] = (),
    action: str | None = None,
) -> CareerProfileReadinessFinding:
    return CareerProfileReadinessFinding(
        code=code,
        impact=impact,
        message=message,
        source_references=references,
        recommended_action=action,
    )


def _trusted_summary(profile: CareerProfile, unresolved_count: int) -> TrustedProfileSummary:
    contact_values = tuple(value for value in (profile.contact.email, profile.contact.phone) if value is not None) if profile.contact else ()
    return TrustedProfileSummary(
        trusted_contact_anchor_count=sum(_is_directly_sourced(value.source) for value in contact_values),
        experience_with_trusted_fact_count=sum(_has_trusted_fact(item.facts) for item in profile.work_experiences),
        education_with_trusted_fact_count=sum(_has_trusted_fact(item.facts) for item in profile.education),
        trusted_skill_count=_trusted_facts_count(profile.skills),
        trusted_tool_count=_trusted_facts_count(profile.tools),
        trusted_certification_count=sum(_is_directly_sourced(item.source) for item in profile.certifications),
        trusted_project_count=sum(_has_trusted_fact(item.facts) for item in profile.projects),
        trusted_publication_count=sum(_is_directly_sourced(item.source) for item in profile.publications),
        unresolved_count=unresolved_count,
    )


def assess_career_profile_readiness(
    profile: CareerProfile,
    *,
    unresolved_evidence: Sequence[UnresolvedEvidence] = (),
    document: CVDocument | None = None,
) -> CareerProfileReadinessResult:
    """Assess whether trusted structured profile data is safe for future CV generation."""

    # Document structure is intentionally not re-parsed or used to infer facts here.
    _ = document
    unresolved = tuple(unresolved_evidence)
    summary = _trusted_summary(profile, len(unresolved))
    blocking: list[CareerProfileReadinessFinding] = []
    review: list[CareerProfileReadinessFinding] = []

    if summary.trusted_contact_anchor_count == 0:
        blocking.append(_finding(
            "missing_contact_anchor",
            ReadinessFindingImpact.BLOCKING,
            "No directly sourced email or phone contact anchor is currently available for safe CV generation.",
            action="Add an explicitly sourced email address or phone number.",
        ))

    substance_count = (
        summary.experience_with_trusted_fact_count
        + summary.education_with_trusted_fact_count
        + summary.trusted_skill_count
        + summary.trusted_tool_count
        + summary.trusted_certification_count
        + summary.trusted_project_count
        + summary.trusted_publication_count
    )
    if substance_count == 0:
        blocking.append(_finding(
            "no_career_substance",
            ReadinessFindingImpact.BLOCKING,
            "No trusted structured career substance is currently available beyond contact information.",
            action="Add only explicitly supported education, experience, skills, tools, projects, certifications, or publications.",
        ))

    experience_unresolved = tuple(item for item in unresolved if item.section_type is SectionType.EXPERIENCE)
    education_unresolved = tuple(item for item in unresolved if item.section_type is SectionType.EDUCATION)
    if experience_unresolved:
        references = _references(experience_unresolved)
        if summary.experience_with_trusted_fact_count == 0:
            blocking.append(_finding(
                "unstructured_experience_evidence",
                ReadinessFindingImpact.BLOCKING,
                "Experience-related source evidence remains unresolved and no structured experience with directly trusted fact support is currently available.",
                references=references,
                action="Review the unresolved experience evidence before generating a CV.",
            ))
        else:
            review.append(_finding(
                "additional_experience_evidence_needs_review",
                ReadinessFindingImpact.REVIEW,
                "Additional experience-related source evidence remains unresolved.",
                references=references,
                action="Review the unresolved experience evidence to reduce omission risk.",
            ))
    if education_unresolved:
        references = _references(education_unresolved)
        if summary.education_with_trusted_fact_count == 0:
            blocking.append(_finding(
                "unstructured_education_evidence",
                ReadinessFindingImpact.BLOCKING,
                "Education-related source evidence remains unresolved and no structured education with directly trusted fact support is currently available.",
                references=references,
                action="Review the unresolved education evidence before generating a CV.",
            ))
        else:
            review.append(_finding(
                "additional_education_evidence_needs_review",
                ReadinessFindingImpact.REVIEW,
                "Additional education-related source evidence remains unresolved.",
                references=references,
                action="Review the unresolved education evidence to reduce omission risk.",
            ))

    meaningful_unresolved = tuple(item for item in unresolved if item.section_type in _MEANINGFUL_UNRESOLVED_SECTIONS)
    if meaningful_unresolved:
        review.append(_finding(
            "unresolved_career_evidence",
            ReadinessFindingImpact.REVIEW,
            "Some source evidence in a career-related section remains unresolved.",
            references=_references(meaningful_unresolved),
            action="Review unresolved source evidence before relying on it in generated CV content.",
        ))

    contact_unresolved = tuple(item for item in unresolved if item.section_type is SectionType.CONTACT)
    if contact_unresolved and summary.trusted_contact_anchor_count > 0:
        review.append(_finding(
            "contact_information_incomplete",
            ReadinessFindingImpact.REVIEW,
            "Some contact-related source evidence remains unresolved, although a direct contact anchor is available.",
            references=_references(contact_unresolved),
            action="Review unresolved contact evidence before finalizing generated contact details.",
        ))

    findings = tuple(blocking + review)
    status = ReadinessStatus.BLOCKED if blocking else ReadinessStatus.NEEDS_REVIEW if review else ReadinessStatus.READY
    return CareerProfileReadinessResult(
        status=status,
        findings=findings,
        blocking_findings=tuple(blocking),
        review_findings=tuple(review),
        trusted_summary=summary,
        unresolved_count=len(unresolved),
    )

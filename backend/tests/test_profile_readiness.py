from datetime import date
import inspect

import pytest
from pydantic import ValidationError

from app.domain.career import (
    CareerFact,
    CareerProfile,
    Certification,
    ContactInfo,
    ContactValue,
    Education,
    FactSource,
    Project,
    Publication,
    SourceType,
    VerificationStatus,
    WorkExperience,
)
from app.domain.document import CVDocument, DocumentFormat, DocumentSource, SectionType
from app.extraction.career import UnresolvedEvidence
from app.services.profile_readiness import ReadinessStatus, assess_career_profile_readiness
from app.services.profile_readiness import service as readiness_service


def source(source_type: SourceType = SourceType.MASTER_CV, reference: str = "page:1:block:1") -> FactSource:
    return FactSource(source_type=source_type, reference=reference, original_text="Synthetic source evidence")


def fact(
    statement: str = "Systems engineering",
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> CareerFact:
    return CareerFact(statement=statement, verification_status=status, source=source())


def contact(*, email: SourceType | None = SourceType.MASTER_CV, phone: SourceType | None = None, website: SourceType | None = None) -> ContactInfo:
    return ContactInfo(
        email=ContactValue(value="person@example.test", source=source(email)) if email else None,
        phone=ContactValue(value="+90 555 010 0101", source=source(phone)) if phone else None,
        website=ContactValue(value="https://example.test", source=source(website)) if website else None,
    )


def experience(status: VerificationStatus = VerificationStatus.VERIFIED) -> WorkExperience:
    return WorkExperience(
        company="Example Works",
        title="Systems Engineer",
        start_date=date(2022, 1, 1),
        end_date=date(2024, 1, 1),
        facts=(fact(status=status),),
    )


def education(status: VerificationStatus = VerificationStatus.VERIFIED) -> Education:
    return Education(institution="Example University", degree="BSc", facts=(fact("Electrical engineering", status),))


def unresolved(section: SectionType | None, reference: str = "page:1:block:9") -> UnresolvedEvidence:
    return UnresolvedEvidence(block_reference=reference, section_type=section, reason="synthetic_ambiguity")


def test_healthy_profile_is_ready_without_findings() -> None:
    profile = CareerProfile(contact=contact(), skills=(fact("Python"),))

    result = assess_career_profile_readiness(profile)

    assert result.status is ReadinessStatus.READY
    assert result.findings == result.blocking_findings == result.review_findings == ()
    assert result.policy_version == "v1"


def test_inferred_facts_and_contacts_do_not_improve_readiness() -> None:
    inferred = CareerProfile(
        contact=contact(email=SourceType.SYSTEM_INFERENCE),
        skills=(fact("Python", VerificationStatus.INFERRED_UNVERIFIED),),
    )

    result = assess_career_profile_readiness(inferred)

    assert result.status is ReadinessStatus.BLOCKED
    assert {item.code for item in result.blocking_findings} == {"missing_contact_anchor", "no_career_substance"}


@pytest.mark.parametrize("profile", [
    CareerProfile(contact=contact(email=SourceType.MASTER_CV), skills=(fact(),)),
    CareerProfile(contact=contact(email=None, phone=SourceType.USER_INPUT), skills=(fact(),)),
])
def test_email_or_phone_is_a_sufficient_direct_contact_anchor(profile: CareerProfile) -> None:
    assert assess_career_profile_readiness(profile).status is ReadinessStatus.READY


def test_website_only_is_not_a_direct_contact_anchor() -> None:
    profile = CareerProfile(contact=contact(email=None, website=SourceType.MASTER_CV), skills=(fact(),))

    assert "missing_contact_anchor" in {item.code for item in assess_career_profile_readiness(profile).blocking_findings}


def test_contact_only_is_blocked_but_non_corporate_profiles_are_supported() -> None:
    contact_only = assess_career_profile_readiness(CareerProfile(contact=contact()))
    graduate = assess_career_profile_readiness(CareerProfile(contact=contact(), education=(education(),), skills=(fact("Python"),)))
    projects = assess_career_profile_readiness(CareerProfile(contact=contact(), projects=(Project(name="Open project", facts=(fact("Project delivery"),)),), skills=(fact("Python"),)))
    academic = assess_career_profile_readiness(CareerProfile(contact=contact(), publications=(Publication(title="Synthetic article", source=source()),)))

    assert contact_only.status is ReadinessStatus.BLOCKED
    assert "no_career_substance" in {item.code for item in contact_only.blocking_findings}
    assert graduate.status is projects.status is academic.status is ReadinessStatus.READY


def test_absence_of_experience_education_certifications_languages_metrics_or_leadership_does_not_block() -> None:
    result = assess_career_profile_readiness(CareerProfile(contact=contact(), skills=(fact("Python"),)))

    assert result.status is ReadinessStatus.READY


@pytest.mark.parametrize(
    ("section", "profile_factory", "blocked_code", "review_code"),
    [
        (SectionType.EXPERIENCE, lambda: CareerProfile(contact=contact(), skills=(fact(),)), "unstructured_experience_evidence", "additional_experience_evidence_needs_review"),
        (SectionType.EDUCATION, lambda: CareerProfile(contact=contact(), skills=(fact(),)), "unstructured_education_evidence", "additional_education_evidence_needs_review"),
    ],
)
def test_unresolved_structural_evidence_blocks_without_trusted_structure_and_needs_review_when_present(section, profile_factory, blocked_code, review_code) -> None:
    base = profile_factory()
    structured = base.model_copy(update={"work_experiences": (experience(),)} if section is SectionType.EXPERIENCE else {"education": (education(),)})

    blocked = assess_career_profile_readiness(base, unresolved_evidence=(unresolved(section),))
    review = assess_career_profile_readiness(structured, unresolved_evidence=(unresolved(section),))

    assert blocked.status is ReadinessStatus.BLOCKED
    assert blocked.blocking_findings[-1].code == blocked_code
    assert review.status is ReadinessStatus.NEEDS_REVIEW
    assert review.review_findings[0].code == review_code


@pytest.mark.parametrize(
    ("section", "field_name", "factory"),
    [
        (SectionType.EXPERIENCE, "work_experiences", experience),
        (SectionType.EDUCATION, "education", education),
    ],
)
def test_only_verified_or_user_provided_structural_facts_support_experience_and_education(section, field_name, factory) -> None:
    inferred = CareerProfile(contact=contact(), skills=(fact(),), **{field_name: (factory(VerificationStatus.INFERRED_UNVERIFIED),)})
    user_provided = CareerProfile(contact=contact(), skills=(fact(),), **{field_name: (factory(VerificationStatus.USER_PROVIDED),)})

    assert assess_career_profile_readiness(inferred, unresolved_evidence=(unresolved(section),)).status is ReadinessStatus.BLOCKED
    assert assess_career_profile_readiness(user_provided, unresolved_evidence=(unresolved(section),)).status is ReadinessStatus.NEEDS_REVIEW


def test_tools_and_certifications_count_as_distinct_career_substance() -> None:
    tool_profile = CareerProfile(contact=contact(), tools=(fact("SAP"),))
    certification_profile = CareerProfile(contact=contact(), certifications=(Certification(name="PMP", source=source()),))

    assert assess_career_profile_readiness(tool_profile).status is ReadinessStatus.READY
    assert assess_career_profile_readiness(certification_profile).status is ReadinessStatus.READY


def test_meaningful_and_contact_unresolved_evidence_need_review_without_fabricating_facts() -> None:
    profile = CareerProfile(contact=contact(), skills=(fact("Python"),))
    items = (unresolved(SectionType.SKILLS, "page:1:block:3"), unresolved(SectionType.CONTACT, "page:1:block:2"), unresolved(None, "page:1:block:1"))

    result = assess_career_profile_readiness(profile, unresolved_evidence=items)

    assert result.status is ReadinessStatus.NEEDS_REVIEW
    assert [item.code for item in result.review_findings] == ["unresolved_career_evidence", "contact_information_incomplete"]
    assert result.review_findings[0].source_references == ("page:1:block:3",)
    assert result.unresolved_count == 3 and result.trusted_summary.unresolved_count == 3
    assert profile.skills == (fact("Python"),)
    assert items[0].block_reference == "page:1:block:3"


def test_unknown_section_evidence_is_conservatively_retained_for_review() -> None:
    result = assess_career_profile_readiness(
        CareerProfile(contact=contact(), skills=(fact(),)),
        unresolved_evidence=(unresolved(SectionType.UNKNOWN, "page:1:block:unknown"),),
    )

    assert result.status is ReadinessStatus.NEEDS_REVIEW
    assert result.review_findings[0].code == "unresolved_career_evidence"
    assert result.review_findings[0].source_references == ("page:1:block:unknown",)


def test_blocked_status_precedes_review_and_finding_collections_reconcile() -> None:
    result = assess_career_profile_readiness(
        CareerProfile(skills=(fact(),)),
        unresolved_evidence=(unresolved(SectionType.SKILLS),),
    )

    assert result.status is ReadinessStatus.BLOCKED
    assert result.findings == result.blocking_findings + result.review_findings
    assert len({(item.code, item.source_references) for item in result.findings}) == len(result.findings)
    assert result.blocking_findings and result.review_findings


def test_document_is_optional_and_never_fabricates_profile_data() -> None:
    profile = CareerProfile(contact=contact(), skills=(fact("Python"),))
    document = CVDocument(source=DocumentSource(filename="synthetic.pdf", document_format=DocumentFormat.PDF))

    without_document = assess_career_profile_readiness(profile)
    with_document = assess_career_profile_readiness(profile, document=document)

    assert without_document == with_document


def test_result_is_immutable_serializable_and_deterministically_ordered() -> None:
    profile = CareerProfile(contact=contact(), skills=(fact(),))
    evidence = (unresolved(SectionType.EDUCATION, "page:2:block:2"), unresolved(SectionType.EXPERIENCE, "page:1:block:2"), unresolved(SectionType.EXPERIENCE, "page:1:block:1"))

    first = assess_career_profile_readiness(profile, unresolved_evidence=evidence)
    second = assess_career_profile_readiness(profile, unresolved_evidence=evidence)

    assert first == second
    assert [item.code for item in first.findings] == ["unstructured_experience_evidence", "unstructured_education_evidence"]
    assert first.findings[0].source_references == ("page:1:block:1", "page:1:block:2")
    serialized = first.model_dump(mode="json")
    assert serialized == second.model_dump(mode="json")
    assert type(first).model_validate(serialized) == first
    with pytest.raises(ValidationError):
        first.status = ReadinessStatus.READY


def test_readiness_has_no_quality_score_job_match_ai_or_coach_dependency() -> None:
    source_text = inspect.getsource(readiness_service)

    assert "analyze_cv_quality" not in source_text
    assert "job_match" not in source_text
    assert "app.ai" not in source_text
    assert "coach" not in source_text.casefold()
    assert "score" not in source_text.casefold()
    assert "CareerFact(" not in source_text

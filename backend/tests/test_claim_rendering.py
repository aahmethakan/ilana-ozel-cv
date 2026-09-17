import copy

import pytest
from pydantic import ValidationError

from app.domain.career import CareerDate
from app.services.claim_rendering import (
    ClaimNotRenderableError,
    ClaimRenderingErrorCode,
    ClaimRenderingMode,
    RenderedClaim,
    render_validated_claim,
)
from app.services.claim_validation import (
    AtomicClaimAssertion,
    ClaimKind,
    ContactFieldAssertion,
    EducationFieldAssertion,
    WorkFieldAssertion,
)
from app.services.evidence_convergence import EducationField, WorkExperienceField
from app.services.generation_context.schemas import EligibleEducation, EligibleWorkExperience
from tests.test_claim_validation import context as claim_context
from tests.test_claim_validation import boolean, date, field, proposal, text


@pytest.fixture
def generation_context():
    return claim_context.__wrapped__()


def assert_error(code: ClaimRenderingErrorCode, callable_) -> None:
    with pytest.raises(ClaimNotRenderableError) as raised:
        callable_()
    assert raised.value.code is code


def test_atomic_and_contact_render_exact_values_not_proposal_prose(generation_context) -> None:
    atomic = AtomicClaimAssertion(evidence_id=generation_context.atomic_claims[0].evidence_id, claim_type="skill", value="SAP")
    rendered = render_validated_claim(generation_context, proposal("Advanced SAP ERP expert", ClaimKind.SKILL, atomic), ClaimRenderingMode.ATOMIC_EXACT)
    assert rendered.text == "SAP"
    email = generation_context.contact.email
    contact = ContactFieldAssertion(evidence_id=email.evidence_id, field_name="email", value=email.value.value)
    assert render_validated_claim(generation_context, proposal("Contact me at another address", ClaimKind.OTHER, contact), ClaimRenderingMode.CONTACT_EXACT).text == "person@example.test"
    phone = generation_context.contact.phone
    two_contacts = proposal("x", ClaimKind.OTHER, contact, ContactFieldAssertion(evidence_id=phone.evidence_id, field_name="phone", value=phone.value.value))
    assert_error(ClaimRenderingErrorCode.UNEXPECTED_ASSERTION, lambda: render_validated_claim(generation_context, two_contacts, ClaimRenderingMode.CONTACT_EXACT))


def test_work_identity_consumes_title_and_company_only(generation_context) -> None:
    work = generation_context.work_experiences[0]
    title = WorkFieldAssertion(evidence_id=work.title.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.TITLE, value="Engineer")
    company = WorkFieldAssertion(evidence_id=work.company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value="ACME")
    rendered = render_validated_claim(generation_context, proposal("Led 100 engineers at ACME", ClaimKind.EXPERIENCE_BULLET, company, title), ClaimRenderingMode.WORK_IDENTITY)
    assert rendered.text == "Engineer — ACME"
    assert "Led" not in rendered.text and "100" not in rendered.text
    location_value = field("work", work.record_id, work.candidate_id, "location", text("Ankara", "page:1:location"))
    location_context = generation_context.model_copy(update={"work_experiences": (work.model_copy(update={"location": location_value}),)})
    location = WorkFieldAssertion(evidence_id=location_value.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.LOCATION, value="Ankara")
    assert_error(ClaimRenderingErrorCode.UNEXPECTED_ASSERTION, lambda: render_validated_claim(location_context, proposal("x", ClaimKind.EXPERIENCE_BULLET, company, title, location), ClaimRenderingMode.WORK_IDENTITY))
    assert_error(ClaimRenderingErrorCode.MISSING_REQUIRED_ASSERTION, lambda: render_validated_claim(generation_context, proposal("x", ClaimKind.EXPERIENCE_BULLET, company), ClaimRenderingMode.WORK_IDENTITY))


def test_cross_lineage_valid_assertions_cannot_be_composed(generation_context) -> None:
    first = generation_context.work_experiences[0]
    second_company = field("work", "work-2", "candidate-2", "company", text("Other Co", "page:2:company"))
    second_title = field("work", "work-2", "candidate-2", "title", text("Analyst", "page:2:title"))
    second = EligibleWorkExperience(evidence_id="work:work-2", record_id="work-2", candidate_id="candidate-2", company=second_company, title=second_title)
    context = generation_context.model_copy(update={"work_experiences": (first, second)})
    title = WorkFieldAssertion(evidence_id=first.title.evidence_id, record_id=first.record_id, candidate_id=first.candidate_id, field_name=WorkExperienceField.TITLE, value="Engineer")
    company = WorkFieldAssertion(evidence_id=second.company.evidence_id, record_id=second.record_id, candidate_id=second.candidate_id, field_name=WorkExperienceField.COMPANY, value="Other Co")
    assert_error(ClaimRenderingErrorCode.LINEAGE_MISMATCH, lambda: render_validated_claim(context, proposal("x", ClaimKind.EXPERIENCE_BULLET, title, company), ClaimRenderingMode.WORK_IDENTITY))


def test_work_date_preserves_precision_and_currentness_rules(generation_context) -> None:
    work = generation_context.work_experiences[0]
    start = WorkFieldAssertion(evidence_id=work.start_date.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.START_DATE, value=CareerDate(year=2024))
    current = WorkFieldAssertion(evidence_id=work.is_current.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.IS_CURRENT, value=True)
    assert render_validated_claim(generation_context, proposal("unsafe", ClaimKind.EXPERIENCE_BULLET, start), ClaimRenderingMode.WORK_DATE).text == "2024"
    assert render_validated_claim(generation_context, proposal("unsafe", ClaimKind.EXPERIENCE_BULLET, start, current), ClaimRenderingMode.WORK_DATE).text == "2024 – Present"
    false_value = field("work", work.record_id, work.candidate_id, "is_current", boolean(False, "page:1:not-current"))
    false_context = generation_context.model_copy(update={"work_experiences": (work.model_copy(update={"is_current": false_value}),)})
    false_current = WorkFieldAssertion(evidence_id=false_value.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.IS_CURRENT, value=False)
    # False is a consumed assertion and must not accidentally render Present.
    assert render_validated_claim(false_context, proposal("unsafe", ClaimKind.EXPERIENCE_BULLET, start, false_current), ClaimRenderingMode.WORK_DATE).text == "2024"


def test_work_date_end_range_and_contradiction_fail_closed(generation_context) -> None:
    work = generation_context.work_experiences[0]
    end_value = date(2024, 5, "page:1:end")
    end = field("work", work.record_id, work.candidate_id, "end_date", end_value)
    updated = work.model_copy(update={"end_date": end})
    context = generation_context.model_copy(update={"work_experiences": (updated,)})
    start_assertion = WorkFieldAssertion(evidence_id=updated.start_date.evidence_id, record_id=updated.record_id, candidate_id=updated.candidate_id, field_name=WorkExperienceField.START_DATE, value=CareerDate(year=2024))
    end_assertion = WorkFieldAssertion(evidence_id=end.evidence_id, record_id=updated.record_id, candidate_id=updated.candidate_id, field_name=WorkExperienceField.END_DATE, value=CareerDate(year=2024, month=5))
    current = WorkFieldAssertion(evidence_id=updated.is_current.evidence_id, record_id=updated.record_id, candidate_id=updated.candidate_id, field_name=WorkExperienceField.IS_CURRENT, value=True)
    assert render_validated_claim(context, proposal("x", ClaimKind.EXPERIENCE_BULLET, start_assertion, end_assertion), ClaimRenderingMode.WORK_DATE).text == "2024 – 2024-05"
    assert_error(ClaimRenderingErrorCode.UNSUPPORTED_FIELD_COMBINATION, lambda: render_validated_claim(context, proposal("x", ClaimKind.EXPERIENCE_BULLET, start_assertion, end_assertion, current), ClaimRenderingMode.WORK_DATE))


def test_education_identity_and_date_are_lineage_scoped(generation_context) -> None:
    education = generation_context.education[0]
    institution = EducationFieldAssertion(evidence_id=education.institution.evidence_id, record_id=education.record_id, candidate_id=education.candidate_id, field_name=EducationField.INSTITUTION, value="Example University")
    degree = EducationFieldAssertion(evidence_id=education.degree.evidence_id, record_id=education.record_id, candidate_id=education.candidate_id, field_name=EducationField.DEGREE, value="BSc")
    rendered = render_validated_claim(generation_context, proposal("Top-ranked university", ClaimKind.EDUCATION, institution, degree), ClaimRenderingMode.EDUCATION_IDENTITY)
    assert rendered.text == "BSc — Example University"
    assert "Top-ranked" not in rendered.text
    assert_error(ClaimRenderingErrorCode.MISSING_REQUIRED_ASSERTION, lambda: render_validated_claim(generation_context, proposal("x", ClaimKind.EDUCATION, degree), ClaimRenderingMode.EDUCATION_IDENTITY))


def test_education_date_and_cross_lineage_fail_closed(generation_context) -> None:
    first = generation_context.education[0]
    second_institution = field("education", "education-2", "candidate-2", "institution", text("Other University", "page:2:institution"))
    second_degree = field("education", "education-2", "candidate-2", "degree", text("MSc", "page:2:degree"))
    second = EligibleEducation(evidence_id="education:education-2", record_id="education-2", candidate_id="candidate-2", institution=second_institution, degree=second_degree)
    context = generation_context.model_copy(update={"education": (first, second)})
    institution = EducationFieldAssertion(evidence_id=first.institution.evidence_id, record_id=first.record_id, candidate_id=first.candidate_id, field_name=EducationField.INSTITUTION, value="Example University")
    degree = EducationFieldAssertion(evidence_id=second.degree.evidence_id, record_id=second.record_id, candidate_id=second.candidate_id, field_name=EducationField.DEGREE, value="MSc")
    assert_error(ClaimRenderingErrorCode.LINEAGE_MISMATCH, lambda: render_validated_claim(context, proposal("x", ClaimKind.EDUCATION, institution, degree), ClaimRenderingMode.EDUCATION_IDENTITY))


def test_mode_mismatch_invalid_claim_and_evidence_consumption_fail_closed(generation_context) -> None:
    atomic = AtomicClaimAssertion(evidence_id=generation_context.atomic_claims[0].evidence_id, claim_type="skill", value="SAP")
    assert_error(ClaimRenderingErrorCode.ASSERTION_SET_MISMATCH, lambda: render_validated_claim(generation_context, proposal("x", ClaimKind.SKILL, atomic), ClaimRenderingMode.WORK_IDENTITY))
    unknown = AtomicClaimAssertion(evidence_id="atomic:unknown", claim_type="skill", value="SAP")
    assert_error(ClaimRenderingErrorCode.CLAIM_VALIDATION_FAILED, lambda: render_validated_claim(generation_context, proposal("x", ClaimKind.SKILL, unknown), ClaimRenderingMode.ATOMIC_EXACT))


def test_rendered_claim_id_serialization_determinism_and_immutability(generation_context) -> None:
    work = generation_context.work_experiences[0]
    company = WorkFieldAssertion(evidence_id=work.company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value="ACME")
    title = WorkFieldAssertion(evidence_id=work.title.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.TITLE, value="Engineer")
    first = proposal("İş deneyimi", ClaimKind.EXPERIENCE_BULLET, company, title)
    second = proposal("İş deneyimi", ClaimKind.EXPERIENCE_BULLET, title, company)
    before_context, before_claim = copy.deepcopy(generation_context.model_dump(mode="json")), copy.deepcopy(first.model_dump(mode="json"))
    rendered_a = render_validated_claim(generation_context, first, ClaimRenderingMode.WORK_IDENTITY)
    rendered_b = render_validated_claim(generation_context, second, ClaimRenderingMode.WORK_IDENTITY)
    assert rendered_a.rendered_claim_id == rendered_b.rendered_claim_id
    assert RenderedClaim.model_validate(rendered_a.model_dump(mode="json")) == rendered_a
    assert set(rendered_a.model_dump()) == {"rendered_claim_id", "text", "claim_kind", "source_claim_id", "supporting_evidence_ids", "rendering_mode", "structured_lineage"}
    assert rendered_a.structured_lineage.record_type == "work"
    assert generation_context.model_dump(mode="json") == before_context
    assert first.model_dump(mode="json") == before_claim
    with pytest.raises(ValidationError):
        RenderedClaim.model_validate({**rendered_a.model_dump(mode="json"), "rendered_claim_id": "rendered-claim:spoofed"})


def test_rendered_identity_ignores_untrusted_proposal_prose(generation_context) -> None:
    work = generation_context.work_experiences[0]
    company = WorkFieldAssertion(evidence_id=work.company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value="ACME")
    title = WorkFieldAssertion(evidence_id=work.title.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.TITLE, value="Engineer")
    first = render_validated_claim(generation_context, proposal("foo", ClaimKind.EXPERIENCE_BULLET, company, title), ClaimRenderingMode.WORK_IDENTITY)
    second = render_validated_claim(generation_context, proposal("bar", ClaimKind.EXPERIENCE_BULLET, company, title), ClaimRenderingMode.WORK_IDENTITY)
    assert first.source_claim_id != second.source_claim_id
    assert first.rendered_claim_id == second.rendered_claim_id
    assert first.text == second.text and first.structured_lineage == second.structured_lineage

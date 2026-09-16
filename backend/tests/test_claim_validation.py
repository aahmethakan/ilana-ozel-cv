import copy

import pytest
from pydantic import ValidationError

from app.domain.career import (
    CareerDate,
    ContactValue,
    FactSource,
    ProvenancedBool,
    ProvenancedCareerDate,
    ProvenancedText,
    SourceType,
    VerificationStatus,
)
from app.services.claim_validation import (
    AtomicClaimAssertion,
    ClaimKind,
    ClaimValidationFindingCode,
    ClaimValidationStatus,
    ContactFieldAssertion,
    EducationFieldAssertion,
    GeneratedClaimProposal,
    WorkFieldAssertion,
    claim_id,
    validate_generated_claim,
)
from app.services.evidence_convergence import EducationField, WorkExperienceField
from app.services.generation_context.schemas import (
    EligibleAtomicClaim,
    EligibleContact,
    EligibleContactField,
    EligibleEducation,
    EligibleStructuredField,
    EligibleWorkExperience,
    GenerationContext,
    atomic_evidence_id,
    contact_field_evidence_id,
    structured_field_evidence_id,
)


def source(reference: str) -> FactSource:
    return FactSource(source_type=SourceType.MASTER_CV, reference=reference, original_text="Synthetic evidence")


def text(value: str, reference: str) -> ProvenancedText:
    return ProvenancedText(value=value, verification_status=VerificationStatus.VERIFIED, value_source=source(reference), evidence_sources=(source(reference),))


def date(year: int, month: int | None, reference: str) -> ProvenancedCareerDate:
    return ProvenancedCareerDate(value=CareerDate(year=year, month=month), verification_status=VerificationStatus.VERIFIED, value_source=source(reference), evidence_sources=(source(reference),))


def boolean(value: bool, reference: str) -> ProvenancedBool:
    return ProvenancedBool(value=value, verification_status=VerificationStatus.VERIFIED, value_source=source(reference), evidence_sources=(source(reference),))


def field(record_type: str, record_id: str, candidate_id: str, field_name: str, value):
    return EligibleStructuredField(
        evidence_id=structured_field_evidence_id(record_type=record_type, record_id=record_id, candidate_id=candidate_id, field_name=field_name, value=value),
        record_type=record_type,
        record_id=record_id,
        candidate_id=candidate_id,
        field_name=field_name,
        value=value,
    )


@pytest.fixture
def context() -> GenerationContext:
    skill_source = source("page:1:skill")
    skill = EligibleAtomicClaim(
        evidence_id=atomic_evidence_id(claim_type="skill", statement="SAP", verification_status=VerificationStatus.VERIFIED, source=skill_source),
        claim_type="skill",
        statement="SAP",
        verification_status=VerificationStatus.VERIFIED,
        source=skill_source,
    )
    contacts = {
        name: EligibleContactField(
            evidence_id=contact_field_evidence_id(field_name=name, value=ContactValue(value=value, source=source(f"page:1:{name}"))),
            field_name=name,
            value=ContactValue(value=value, source=source(f"page:1:{name}")),
        )
        for name, value in (("email", "person@example.test"), ("phone", "+90-555-000-0000"), ("website", "https://example.test"))
    }
    work_id, work_candidate = "work-1", "work-candidate-1"
    company = field("work", work_id, work_candidate, "company", text("ACME", "page:1:company"))
    title = field("work", work_id, work_candidate, "title", text("Engineer", "page:1:title"))
    start = field("work", work_id, work_candidate, "start_date", date(2024, None, "page:1:start"))
    current = field("work", work_id, work_candidate, "is_current", boolean(True, "page:1:current"))
    education_id, education_candidate = "education-1", "education-candidate-1"
    institution = field("education", education_id, education_candidate, "institution", text("Example University", "page:1:institution"))
    degree = field("education", education_id, education_candidate, "degree", text("BSc", "page:1:degree"))
    field_of_study = field("education", education_id, education_candidate, "field_of_study", text("Engineering", "page:1:field"))
    return GenerationContext(
        contact=EligibleContact(**contacts),
        atomic_claims=(skill,),
        work_experiences=(EligibleWorkExperience(evidence_id=f"work:{work_id}", record_id=work_id, candidate_id=work_candidate, company=company, title=title, start_date=start, is_current=current),),
        education=(EligibleEducation(evidence_id=f"education:{education_id}", record_id=education_id, candidate_id=education_candidate, institution=institution, degree=degree, field_of_study=field_of_study),),
    )


def proposal(text_value: str, kind: ClaimKind, *assertions) -> GeneratedClaimProposal:
    assertions_tuple = tuple(assertions)
    return GeneratedClaimProposal(claim_id=claim_id(claim_kind=kind, text=text_value, assertions=assertions_tuple), text=text_value, claim_kind=kind, assertions=assertions_tuple)


def result_code(context: GenerationContext, claim: GeneratedClaimProposal) -> ClaimValidationFindingCode:
    result = validate_generated_claim(context, claim)
    assert result.status is ClaimValidationStatus.INVALID
    assert len(result.findings) == 1
    return result.findings[0].code


@pytest.mark.parametrize("assertion", [
    AtomicClaimAssertion(evidence_id="atomic:x", claim_type="skill", value="Python"),
    WorkFieldAssertion(evidence_id="work-field:x", record_id="work", candidate_id="candidate", field_name=WorkExperienceField.TITLE, value="Engineer"),
    EducationFieldAssertion(evidence_id="education-field:x", record_id="education", candidate_id="candidate", field_name=EducationField.DEGREE, value="BSc"),
    ContactFieldAssertion(evidence_id="contact-field:x", field_name="email", value="person@example.test"),
])
def test_all_discriminator_variants_round_trip(assertion) -> None:
    claim = proposal("Synthetic", ClaimKind.OTHER, assertion)
    assert GeneratedClaimProposal.model_validate(claim.model_dump(mode="json")) == claim


def test_schema_rejects_invalid_discriminators_and_strict_shapes() -> None:
    with pytest.raises(ValidationError):
        GeneratedClaimProposal.model_validate({"claim_id": "claim:x", "text": "x", "claim_kind": "other", "assertions": ({"evidence_id": "x"},)})
    with pytest.raises(ValidationError):
        GeneratedClaimProposal.model_validate({"claim_id": "claim:x", "text": "x", "claim_kind": "other", "assertions": ({"assertion_kind": "unknown", "evidence_id": "x"},)})
    with pytest.raises(ValidationError):
        WorkFieldAssertion(evidence_id="x", record_type="education", record_id="r", candidate_id="c", field_name=WorkExperienceField.TITLE, value="Engineer")
    with pytest.raises(ValidationError):
        AtomicClaimAssertion(evidence_id="x", claim_type="skill", value="Python", unexpected=True)
    with pytest.raises(ValidationError):
        WorkFieldAssertion(evidence_id="x", record_id="r", candidate_id="c", field_name=WorkExperienceField.IS_CURRENT, value="true")


def test_claim_shape_and_id_invariants() -> None:
    assertion = AtomicClaimAssertion(evidence_id="atomic:x", claim_type="skill", value="Python")
    with pytest.raises(ValidationError):
        GeneratedClaimProposal(claim_id="claim:x", text="   ", claim_kind=ClaimKind.SKILL, assertions=(assertion,))
    with pytest.raises(ValidationError):
        GeneratedClaimProposal(claim_id="claim:x", text="x", claim_kind=ClaimKind.SKILL, assertions=())
    with pytest.raises(ValidationError):
        proposal("Python", ClaimKind.SKILL, assertion, assertion)
    with pytest.raises(ValidationError):
        GeneratedClaimProposal(claim_id="claim:spoofed", text="Python", claim_kind=ClaimKind.SKILL, assertions=(assertion,))


def test_atomic_validation_is_exact_and_has_no_value_fallback(context: GenerationContext) -> None:
    evidence = context.atomic_claims[0]
    valid = proposal("SAP", ClaimKind.SKILL, AtomicClaimAssertion(evidence_id=evidence.evidence_id, claim_type="skill", value="SAP"))
    assert validate_generated_claim(context, valid).status is ClaimValidationStatus.VALID
    assert result_code(context, proposal("SAP ERP", ClaimKind.SKILL, AtomicClaimAssertion(evidence_id=evidence.evidence_id, claim_type="skill", value="SAP ERP"))) is ClaimValidationFindingCode.VALUE_MISMATCH
    assert result_code(context, proposal("SAP", ClaimKind.SKILL, AtomicClaimAssertion(evidence_id=evidence.evidence_id, claim_type="tool", value="SAP"))) is ClaimValidationFindingCode.FIELD_MISMATCH
    assert result_code(context, proposal("SAP", ClaimKind.SKILL, AtomicClaimAssertion(evidence_id="atomic:unknown", claim_type="skill", value="SAP"))) is ClaimValidationFindingCode.UNKNOWN_EVIDENCE


def test_work_assertions_require_exact_field_lineage_and_value(context: GenerationContext) -> None:
    work = context.work_experiences[0]
    company, title = work.company, work.title
    exact = WorkFieldAssertion(evidence_id=company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value="ACME")
    assert validate_generated_claim(context, proposal("ACME", ClaimKind.EXPERIENCE_BULLET, exact)).status is ClaimValidationStatus.VALID
    assert result_code(context, proposal("ACME", ClaimKind.EXPERIENCE_BULLET, WorkFieldAssertion(evidence_id=company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.TITLE, value="ACME"))) is ClaimValidationFindingCode.FIELD_MISMATCH
    assert result_code(context, proposal("ACME", ClaimKind.EXPERIENCE_BULLET, WorkFieldAssertion(evidence_id=company.evidence_id, record_id="other", candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value="ACME"))) is ClaimValidationFindingCode.LINEAGE_MISMATCH
    assert result_code(context, proposal("ACME", ClaimKind.EXPERIENCE_BULLET, WorkFieldAssertion(evidence_id=company.evidence_id, record_id=work.record_id, candidate_id="other", field_name=WorkExperienceField.COMPANY, value="ACME"))) is ClaimValidationFindingCode.LINEAGE_MISMATCH
    assert result_code(context, proposal("Engineer", ClaimKind.EXPERIENCE_BULLET, WorkFieldAssertion(evidence_id=title.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.TITLE, value="Senior Engineer"))) is ClaimValidationFindingCode.VALUE_MISMATCH


def test_education_assertions_are_field_and_domain_scoped(context: GenerationContext) -> None:
    education = context.education[0]
    degree = EducationFieldAssertion(evidence_id=education.degree.evidence_id, record_id=education.record_id, candidate_id=education.candidate_id, field_name=EducationField.DEGREE, value="BSc")
    assert validate_generated_claim(context, proposal("BSc", ClaimKind.EDUCATION, degree)).status is ClaimValidationStatus.VALID
    assert result_code(context, proposal("BSc", ClaimKind.EDUCATION, EducationFieldAssertion(evidence_id=education.institution.evidence_id, record_id=education.record_id, candidate_id=education.candidate_id, field_name=EducationField.DEGREE, value="BSc"))) is ClaimValidationFindingCode.FIELD_MISMATCH
    work = context.work_experiences[0]
    assert result_code(context, proposal("ACME", ClaimKind.EDUCATION, EducationFieldAssertion(evidence_id=work.company.evidence_id, record_id=education.record_id, candidate_id=education.candidate_id, field_name=EducationField.INSTITUTION, value="ACME"))) is ClaimValidationFindingCode.LINEAGE_MISMATCH


@pytest.mark.parametrize("field_name", ["email", "phone", "website"])
def test_contact_assertions_are_exact_and_provenance_scoped(context: GenerationContext, field_name: str) -> None:
    evidence = getattr(context.contact, field_name)
    exact = ContactFieldAssertion(evidence_id=evidence.evidence_id, field_name=field_name, value=evidence.value.value)
    assert validate_generated_claim(context, proposal(evidence.value.value, ClaimKind.OTHER, exact)).status is ClaimValidationStatus.VALID
    other = "phone" if field_name == "email" else "email"
    assert result_code(context, proposal("x", ClaimKind.OTHER, ContactFieldAssertion(evidence_id=evidence.evidence_id, field_name=other, value=evidence.value.value))) is ClaimValidationFindingCode.FIELD_MISMATCH
    assert result_code(context, proposal("x", ClaimKind.OTHER, ContactFieldAssertion(evidence_id=evidence.evidence_id, field_name=field_name, value="different@example.test"))) is ClaimValidationFindingCode.VALUE_MISMATCH


def test_cross_kind_and_finding_precedence_are_deterministic(context: GenerationContext) -> None:
    company = context.work_experiences[0].company
    atomic_on_work = AtomicClaimAssertion(evidence_id=company.evidence_id, claim_type="skill", value="ACME")
    assert result_code(context, proposal("ACME", ClaimKind.SKILL, atomic_on_work)) is ClaimValidationFindingCode.EVIDENCE_KIND_MISMATCH
    contact = context.contact.email
    work_on_contact = WorkFieldAssertion(evidence_id=contact.evidence_id, record_id="wrong", candidate_id="wrong", field_name=WorkExperienceField.COMPANY, value="ACME")
    assert result_code(context, proposal("ACME", ClaimKind.EXPERIENCE_BULLET, work_on_contact)) is ClaimValidationFindingCode.EVIDENCE_KIND_MISMATCH
    unknown = AtomicClaimAssertion(evidence_id="atomic:does-not-exist", claim_type="wrong", value="wrong")
    assert result_code(context, proposal("x", ClaimKind.OTHER, unknown)) is ClaimValidationFindingCode.UNKNOWN_EVIDENCE


def test_currentness_and_dates_preserve_exact_types_and_precision(context: GenerationContext) -> None:
    work = context.work_experiences[0]
    current = WorkFieldAssertion(evidence_id=work.is_current.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.IS_CURRENT, value=True)
    assert validate_generated_claim(context, proposal("Current", ClaimKind.EXPERIENCE_BULLET, current)).status is ClaimValidationStatus.VALID
    start = WorkFieldAssertion(evidence_id=work.start_date.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.START_DATE, value=CareerDate(year=2024))
    assert validate_generated_claim(context, proposal("2024", ClaimKind.EXPERIENCE_BULLET, start)).status is ClaimValidationStatus.VALID
    month = WorkFieldAssertion(evidence_id=work.start_date.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.START_DATE, value=CareerDate(year=2024, month=5))
    assert result_code(context, proposal("2024-05", ClaimKind.EXPERIENCE_BULLET, month)) is ClaimValidationFindingCode.VALUE_MISMATCH
    end_date_as_currentness = WorkFieldAssertion(evidence_id=work.start_date.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.IS_CURRENT, value=True)
    assert result_code(context, proposal("Current", ClaimKind.EXPERIENCE_BULLET, end_date_as_currentness)) is ClaimValidationFindingCode.FIELD_MISMATCH
    with pytest.raises(ValidationError):
        WorkFieldAssertion(evidence_id=work.is_current.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.IS_CURRENT, value="true")


def test_claim_composition_is_deterministic_and_does_not_mutate_inputs(context: GenerationContext) -> None:
    atomic = AtomicClaimAssertion(evidence_id=context.atomic_claims[0].evidence_id, claim_type="skill", value="SAP")
    work = context.work_experiences[0]
    work_assertion = WorkFieldAssertion(evidence_id=work.company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value="ACME")
    contact = ContactFieldAssertion(evidence_id=context.contact.email.evidence_id, field_name="email", value="person@example.test")
    first = proposal("Synthetic", ClaimKind.OTHER, atomic, work_assertion, contact)
    second = proposal("Synthetic", ClaimKind.OTHER, contact, atomic, work_assertion)
    assert first.claim_id == second.claim_id
    assert first.supporting_evidence_ids == tuple(sorted({atomic.evidence_id, work_assertion.evidence_id, contact.evidence_id}))
    before = copy.deepcopy(context.model_dump(mode="json"))
    result = validate_generated_claim(context, first)
    assert result.status is ClaimValidationStatus.VALID
    assert type(result).model_validate(result.model_dump(mode="json")) == result
    assert context.model_dump(mode="json") == before


def test_unicode_claim_and_assertion_serialization_round_trip(context: GenerationContext) -> None:
    assertion = AtomicClaimAssertion(evidence_id=context.atomic_claims[0].evidence_id, claim_type="skill", value="SAP")
    claim = proposal("İş geliştirme: SAP", ClaimKind.SUMMARY, assertion)
    restored = GeneratedClaimProposal.model_validate(claim.model_dump(mode="json"))
    assert restored == claim
    assert validate_generated_claim(context, restored).status is ClaimValidationStatus.VALID


@pytest.mark.parametrize("text_value", ["Led 100 engineers at ACME", "Award-winning Commissioning Engineer"])
def test_valid_assertion_matching_does_not_claim_semantic_or_export_safety(context: GenerationContext, text_value: str) -> None:
    work = context.work_experiences[0]
    assertion = WorkFieldAssertion(evidence_id=work.company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value="ACME")
    result = validate_generated_claim(context, proposal(text_value, ClaimKind.EXPERIENCE_BULLET, assertion))
    assert result.status is ClaimValidationStatus.VALID
    assert not any(hasattr(result, name) for name in ("is_export_safe", "is_fully_verified", "is_semantically_entailed", "is_factually_true"))

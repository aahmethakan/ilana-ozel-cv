import pytest
from pydantic import ValidationError

from app.domain.career import CareerFact, ContactInfo, ContactValue, SourceType, VerificationStatus
from app.services.generation_context.schemas import EligibleContactField
from app.services.career_context import build_unified_career_context
from app.services.generation_context import GenerationContext, GenerationContextNotReadyError, build_generation_context
from app.services.generation_context.service import _eligible_contact
from tests.test_career_context import atomic_ready, source, structured_inputs


def test_ready_context_projects_only_eligible_atomic_and_structured_evidence() -> None:
    assembly, convergence, coverage = structured_inputs()
    profile = atomic_ready().model_copy(update={
        "tools": (
            CareerFact(statement="SAP", verification_status=VerificationStatus.VERIFIED, source=source("page:1:sap")),
            CareerFact(statement="SAP ERP", verification_status=VerificationStatus.INFERRED_UNVERIFIED, source=source("page:1:sap-erp")),
        ),
    })
    generated = build_generation_context(build_unified_career_context(atomic_profile=profile, structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage))

    assert [item.statement for item in generated.atomic_claims] == ["Python", "SAP"]
    assert generated.work_experiences[0].company.value.value == "ACME"
    assert generated.work_experiences[0].title.value.value == "Engineer"
    assert generated.work_experiences[0].location is None
    assert generated.work_experiences[0].evidence_id.startswith("work:")
    assert generated.work_experiences[0].company.evidence_id.startswith("work-field:")
    assert generated.work_experiences[0].company.evidence_id != generated.work_experiences[0].title.evidence_id
    assert generated.find_eligible_evidence(generated.work_experiences[0].company.evidence_id) == generated.work_experiences[0].company
    assert GenerationContext.model_validate(generated.model_dump(mode="json")) == generated


def test_non_ready_context_is_refused_without_projecting_partial_record() -> None:
    assembly, convergence, coverage = structured_inputs(partial=True)
    context = build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    with pytest.raises(GenerationContextNotReadyError):
        build_generation_context(context)


def test_eligible_models_are_strict_and_immutable() -> None:
    assembly, convergence, coverage = structured_inputs()
    generated = build_generation_context(build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage))
    with pytest.raises(ValidationError):
        generated.atomic_claims = ()


def test_contact_fields_are_independent_deterministic_eligible_evidence() -> None:
    assembly, convergence, coverage = structured_inputs()
    profile = atomic_ready().model_copy(update={
        "contact": ContactInfo(
            email=ContactValue(value="same@example.test", source=source("page:1:email")),
            phone=ContactValue(value="same@example.test", source=source("page:1:phone")),
            website=ContactValue(value="https://example.test", source=source("page:1:website")),
        ),
    })
    unified = build_unified_career_context(atomic_profile=profile, structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    generated = build_generation_context(unified)
    assert generated.contact is not None
    assert generated.contact.email.evidence_id.startswith("contact-field:")
    assert generated.contact.email.evidence_id != generated.contact.phone.evidence_id
    assert generated.contact.email.evidence_id not in {item.evidence_id for item in generated.atomic_claims}
    assert generated.find_eligible_evidence(generated.contact.website.evidence_id) is generated.contact.website
    assert GenerationContext.model_validate(generated.model_dump(mode="json")) == generated
    with pytest.raises(ValidationError):
        EligibleContactField(evidence_id="contact-field:spoofed", field_name="email", value=profile.contact.email)


def test_contact_projection_reuses_direct_source_policy() -> None:
    profile = atomic_ready().model_copy(update={
        "contact": ContactInfo(
            email=ContactValue(
                value="not-eligible@example.test",
                source=source("page:1:inferred").model_copy(update={"source_type": SourceType.SYSTEM_INFERENCE}),
            ),
        ),
    })
    assert _eligible_contact(profile) is None

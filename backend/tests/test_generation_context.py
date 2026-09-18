import pytest
from pydantic import ValidationError

from app.domain.career import CareerFact, ContactInfo, ContactValue, FactSource, SourceType, VerificationStatus
from app.domain.career.work_fact_association import WorkFactAssociation, work_fact_association_id
from app.services.generation_context.schemas import EligibleContactField, EligibleStructuredField, EligibleWorkExperience, structured_field_evidence_id
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


def test_exact_trusted_work_fact_association_projects_into_generation_context() -> None:
    assembly, convergence, coverage = structured_inputs()
    unified = build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    baseline = build_generation_context(unified)
    atomic = baseline.atomic_claims[0]
    work = baseline.work_experiences[0]
    source = FactSource(source_type=SourceType.USER_INPUT)
    association = WorkFactAssociation(
        association_id=work_fact_association_id(atomic_evidence_id=atomic.evidence_id, work_record_id=work.record_id, work_candidate_id=work.candidate_id, verification_status=VerificationStatus.USER_PROVIDED, source=source),
        atomic_evidence_id=atomic.evidence_id, work_record_id=work.record_id, work_candidate_id=work.candidate_id,
        verification_status=VerificationStatus.USER_PROVIDED, source=source,
    )
    generated = build_generation_context(unified, work_fact_associations=(association,))
    assert len(generated.work_fact_associations) == 1
    projected = generated.work_fact_associations[0]
    assert (projected.association_id, projected.atomic_evidence_id, projected.work_record_id, projected.work_candidate_id) == (association.association_id, atomic.evidence_id, work.record_id, work.candidate_id)


def test_generation_context_rejects_association_evidence_id_collision() -> None:
    assembly, convergence, coverage = structured_inputs()
    unified = build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    baseline = build_generation_context(unified)
    atomic = baseline.atomic_claims[0]
    work = baseline.work_experiences[0]
    source = FactSource(source_type=SourceType.USER_INPUT)
    association = WorkFactAssociation(association_id=work_fact_association_id(atomic_evidence_id=atomic.evidence_id, work_record_id=work.record_id, work_candidate_id=work.candidate_id, verification_status=VerificationStatus.USER_PROVIDED, source=source), atomic_evidence_id=atomic.evidence_id, work_record_id=work.record_id, work_candidate_id=work.candidate_id, verification_status=VerificationStatus.USER_PROVIDED, source=source)
    projected = build_generation_context(unified, work_fact_associations=(association,)).work_fact_associations[0]
    with pytest.raises(ValidationError):
        GenerationContext(atomic_claims=baseline.atomic_claims, work_fact_associations=(projected.model_copy(update={"association_evidence_id": atomic.evidence_id}),))


def test_association_with_missing_eligible_atomic_endpoint_does_not_project() -> None:
    assembly, convergence, coverage = structured_inputs()
    unified = build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    baseline = build_generation_context(unified)
    work = baseline.work_experiences[0]
    source = FactSource(source_type=SourceType.USER_INPUT)
    missing_atomic_id = "atomic:missing"
    association = WorkFactAssociation(association_id=work_fact_association_id(atomic_evidence_id=missing_atomic_id, work_record_id=work.record_id, work_candidate_id=work.candidate_id, verification_status=VerificationStatus.USER_PROVIDED, source=source), atomic_evidence_id=missing_atomic_id, work_record_id=work.record_id, work_candidate_id=work.candidate_id, verification_status=VerificationStatus.USER_PROVIDED, source=source)
    generated = build_generation_context(unified, work_fact_associations=(association,))
    assert generated.work_fact_associations == ()
    assert missing_atomic_id not in {claim.evidence_id for claim in generated.atomic_claims}


def test_association_with_missing_eligible_work_endpoint_does_not_project() -> None:
    assembly, convergence, coverage = structured_inputs()
    unified = build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    baseline = build_generation_context(unified)
    atomic = baseline.atomic_claims[0]
    source = FactSource(source_type=SourceType.USER_INPUT)
    association = WorkFactAssociation(association_id=work_fact_association_id(atomic_evidence_id=atomic.evidence_id, work_record_id="missing-record", work_candidate_id="missing-candidate", verification_status=VerificationStatus.USER_PROVIDED, source=source), atomic_evidence_id=atomic.evidence_id, work_record_id="missing-record", work_candidate_id="missing-candidate", verification_status=VerificationStatus.USER_PROVIDED, source=source)
    generated = build_generation_context(unified, work_fact_associations=(association,))
    assert generated.work_fact_associations == ()
    assert ("missing-record", "missing-candidate") not in {(work.record_id, work.candidate_id) for work in generated.work_experiences}


def test_cross_pair_work_lineage_does_not_project_association(monkeypatch: pytest.MonkeyPatch) -> None:
    assembly, convergence, coverage = structured_inputs()
    unified = build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    baseline = build_generation_context(unified)
    atomic = baseline.atomic_claims[0]
    original = baseline.work_experiences[0]
    def valid_work(record_id: str, candidate_id: str) -> EligibleWorkExperience:
        def field(name, value):
            return EligibleStructuredField(evidence_id=structured_field_evidence_id(record_type="work", record_id=record_id, candidate_id=candidate_id, field_name=name, value=value), record_type="work", record_id=record_id, candidate_id=candidate_id, field_name=name, value=value)
        return EligibleWorkExperience(evidence_id=f"work:{record_id}", record_id=record_id, candidate_id=candidate_id, company=field("company", original.company.value), title=field("title", original.title.value))
    first = valid_work("R1", "C1")
    second = valid_work("R2", "C2")
    monkeypatch.setattr("app.services.generation_context.service._work_entries", lambda _: (first, second))
    source = FactSource(source_type=SourceType.USER_INPUT)
    association = WorkFactAssociation(association_id=work_fact_association_id(atomic_evidence_id=atomic.evidence_id, work_record_id="R1", work_candidate_id="C2", verification_status=VerificationStatus.USER_PROVIDED, source=source), atomic_evidence_id=atomic.evidence_id, work_record_id="R1", work_candidate_id="C2", verification_status=VerificationStatus.USER_PROVIDED, source=source)
    assert build_generation_context(unified, work_fact_associations=(association,)).work_fact_associations == ()


def test_empty_work_fact_association_input_remains_empty() -> None:
    assembly, convergence, coverage = structured_inputs()
    context = build_unified_career_context(atomic_profile=atomic_ready(), structured_assembly=assembly, evidence_convergence=convergence, evidence_coverage=coverage)
    assert build_generation_context(context, work_fact_associations=()).work_fact_associations == ()


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

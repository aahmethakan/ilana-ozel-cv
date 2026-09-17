import pytest

from app.services.claim_rendering import ClaimRenderingMode, RenderedClaim, rendered_claim_id, render_validated_claim
from app.services.claim_validation import AtomicClaimAssertion, ClaimKind, EducationFieldAssertion, WorkFieldAssertion
from app.services.evidence_convergence import EducationField, WorkExperienceField
from app.services.section_composition import ComposedSection, SectionCompositionError, SectionCompositionErrorCode, SectionType, compose_education_entry, compose_education_section, compose_work_entry, compose_work_section
from app.services.section_composition.schemas import section_id
from tests.test_claim_rendering import generation_context, proposal
from tests.test_claim_validation import date, field, text
from app.services.generation_context.schemas import EligibleEducation, EligibleWorkExperience


def work_claims(generation_context):
    work = generation_context.work_experiences[0]
    company = WorkFieldAssertion(evidence_id=work.company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value="ACME")
    title = WorkFieldAssertion(evidence_id=work.title.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.TITLE, value="Engineer")
    identity = render_validated_claim(generation_context, proposal("unsafe", ClaimKind.EXPERIENCE_BULLET, title, company), ClaimRenderingMode.WORK_IDENTITY)
    start = WorkFieldAssertion(evidence_id=work.start_date.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.START_DATE, value=work.start_date.value.value)
    date = render_validated_claim(generation_context, proposal("unsafe", ClaimKind.EXPERIENCE_BULLET, start), ClaimRenderingMode.WORK_DATE)
    return identity, date


def education_claims(generation_context):
    education = generation_context.education[0]
    institution = EducationFieldAssertion(evidence_id=education.institution.evidence_id, record_id=education.record_id, candidate_id=education.candidate_id, field_name=EducationField.INSTITUTION, value="Example University")
    degree = EducationFieldAssertion(evidence_id=education.degree.evidence_id, record_id=education.record_id, candidate_id=education.candidate_id, field_name=EducationField.DEGREE, value="BSc")
    identity = render_validated_claim(generation_context, proposal("unsafe", ClaimKind.EDUCATION, institution, degree), ClaimRenderingMode.EDUCATION_IDENTITY)
    return identity


_WORK_FIXTURES = {
    ("R1", "C1"): ("Engineer", "Alpha Manufacturing", 2022, 2024),
    ("R1", "C2"): ("Engineer", "Alpha Manufacturing", 2022, 2024),
    ("R2", "C1"): ("Project Engineer", "Beta Systems", 2024, 2025),
}
_EDUCATION_FIXTURES = {
    ("E1", "C1"): ("Mechanical Engineering", "Alpha University", 2018, 2022),
    ("E1", "C2"): ("Mechanical Engineering", "Alpha University", 2018, 2022),
    ("E2", "C1"): ("Üretim Sistemleri", "Beta University", 2023, 2025),
}


def make_work_rendered_claim(generation_context, record_id: str, candidate_id: str, mode: ClaimRenderingMode):
    title_value, company_value, start_year, end_year = _WORK_FIXTURES[(record_id, candidate_id)]
    company = field("work", record_id, candidate_id, "company", text(company_value, f"synthetic:{record_id}:{candidate_id}:company"))
    title = field("work", record_id, candidate_id, "title", text(title_value, f"synthetic:{record_id}:{candidate_id}:title"))
    start = field("work", record_id, candidate_id, "start_date", date(start_year, None, f"synthetic:{record_id}:{candidate_id}:start"))
    end = field("work", record_id, candidate_id, "end_date", date(end_year, None, f"synthetic:{record_id}:{candidate_id}:end"))
    work = EligibleWorkExperience(evidence_id=f"work:{record_id}", record_id=record_id, candidate_id=candidate_id, company=company, title=title, start_date=start, end_date=end)
    context = generation_context.model_copy(update={"work_experiences": (work,)})
    if mode is ClaimRenderingMode.WORK_IDENTITY:
        assertions = (WorkFieldAssertion(evidence_id=title.evidence_id, record_id=record_id, candidate_id=candidate_id, field_name=WorkExperienceField.TITLE, value=title_value), WorkFieldAssertion(evidence_id=company.evidence_id, record_id=record_id, candidate_id=candidate_id, field_name=WorkExperienceField.COMPANY, value=company_value))
    else:
        assertions = (WorkFieldAssertion(evidence_id=start.evidence_id, record_id=record_id, candidate_id=candidate_id, field_name=WorkExperienceField.START_DATE, value=start.value.value), WorkFieldAssertion(evidence_id=end.evidence_id, record_id=record_id, candidate_id=candidate_id, field_name=WorkExperienceField.END_DATE, value=end.value.value))
    return render_validated_claim(context, proposal("synthetic", ClaimKind.EXPERIENCE_BULLET, *assertions), mode)


def make_education_rendered_claim(generation_context, record_id: str, candidate_id: str, mode: ClaimRenderingMode):
    degree_value, institution_value, start_year, end_year = _EDUCATION_FIXTURES[(record_id, candidate_id)]
    institution = field("education", record_id, candidate_id, "institution", text(institution_value, f"synthetic:{record_id}:{candidate_id}:institution"))
    degree = field("education", record_id, candidate_id, "degree", text(degree_value, f"synthetic:{record_id}:{candidate_id}:degree"))
    start = field("education", record_id, candidate_id, "start_date", date(start_year, None, f"synthetic:{record_id}:{candidate_id}:start"))
    end = field("education", record_id, candidate_id, "end_date", date(end_year, None, f"synthetic:{record_id}:{candidate_id}:end"))
    education = EligibleEducation(evidence_id=f"education:{record_id}", record_id=record_id, candidate_id=candidate_id, institution=institution, degree=degree, start_date=start, end_date=end)
    context = generation_context.model_copy(update={"education": (education,)})
    if mode is ClaimRenderingMode.EDUCATION_IDENTITY:
        assertions = (EducationFieldAssertion(evidence_id=institution.evidence_id, record_id=record_id, candidate_id=candidate_id, field_name=EducationField.INSTITUTION, value=institution_value), EducationFieldAssertion(evidence_id=degree.evidence_id, record_id=record_id, candidate_id=candidate_id, field_name=EducationField.DEGREE, value=degree_value))
    else:
        assertions = (EducationFieldAssertion(evidence_id=start.evidence_id, record_id=record_id, candidate_id=candidate_id, field_name=EducationField.START_DATE, value=start.value.value), EducationFieldAssertion(evidence_id=end.evidence_id, record_id=record_id, candidate_id=candidate_id, field_name=EducationField.END_DATE, value=end.value.value))
    return render_validated_claim(context, proposal("synthetic", ClaimKind.EDUCATION, *assertions), mode)


def test_multilineage_fixture_helpers_are_exact_and_deterministic(generation_context):
    work_r1c1 = make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_IDENTITY)
    assert (work_r1c1.structured_lineage.record_id, work_r1c1.structured_lineage.candidate_id) == ("R1", "C1")
    assert make_work_rendered_claim(generation_context, "R1", "C2", ClaimRenderingMode.WORK_IDENTITY).structured_lineage.candidate_id == "C2"
    assert make_work_rendered_claim(generation_context, "R2", "C1", ClaimRenderingMode.WORK_IDENTITY).structured_lineage.record_id == "R2"
    assert make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_DATE).structured_lineage == work_r1c1.structured_lineage
    education_e1c1 = make_education_rendered_claim(generation_context, "E1", "C1", ClaimRenderingMode.EDUCATION_IDENTITY)
    assert (education_e1c1.structured_lineage.record_id, education_e1c1.structured_lineage.candidate_id) == ("E1", "C1")
    assert make_education_rendered_claim(generation_context, "E1", "C2", ClaimRenderingMode.EDUCATION_IDENTITY).structured_lineage.candidate_id == "C2"
    assert make_education_rendered_claim(generation_context, "E2", "C1", ClaimRenderingMode.EDUCATION_IDENTITY).structured_lineage.record_id == "E2"
    assert make_education_rendered_claim(generation_context, "E1", "C1", ClaimRenderingMode.EDUCATION_DATE).structured_lineage == education_e1c1.structured_lineage
    assert make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_IDENTITY) == work_r1c1


def test_work_lineage_matrix_and_duplicate_reuse(generation_context):
    identity = make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_IDENTITY)
    date_same = make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_DATE)
    assert compose_work_entry((identity,)).record_id == "R1"
    assert compose_work_entry((identity, date_same)).candidate_id == "C1"
    for date_claim in (make_work_rendered_claim(generation_context, "R2", "C1", ClaimRenderingMode.WORK_DATE), make_work_rendered_claim(generation_context, "R1", "C2", ClaimRenderingMode.WORK_DATE)):
        with pytest.raises(SectionCompositionError) as raised: compose_work_entry((identity, date_claim))
        assert raised.value.code is SectionCompositionErrorCode.LINEAGE_MISMATCH
    for claims, code in (((date_same,), SectionCompositionErrorCode.MISSING_IDENTITY), ((identity, identity), SectionCompositionErrorCode.DUPLICATE_SLOT), ((identity, date_same, date_same), SectionCompositionErrorCode.DUPLICATE_SLOT)):
        with pytest.raises(SectionCompositionError) as raised: compose_work_entry(claims)
        assert raised.value.code is code
    first, second = compose_work_entry((identity,)), compose_work_entry((identity, date_same))
    assert first.entry_id != second.entry_id
    with pytest.raises(SectionCompositionError) as raised: compose_work_section((first, second))
    assert raised.value.code is SectionCompositionErrorCode.DUPLICATE_CLAIM


def test_education_lineage_matrix_and_duplicate_reuse(generation_context):
    identity = make_education_rendered_claim(generation_context, "E1", "C1", ClaimRenderingMode.EDUCATION_IDENTITY)
    date_same = make_education_rendered_claim(generation_context, "E1", "C1", ClaimRenderingMode.EDUCATION_DATE)
    assert compose_education_entry((identity, date_same)).record_id == "E1"
    for date_claim in (make_education_rendered_claim(generation_context, "E2", "C1", ClaimRenderingMode.EDUCATION_DATE), make_education_rendered_claim(generation_context, "E1", "C2", ClaimRenderingMode.EDUCATION_DATE)):
        with pytest.raises(SectionCompositionError) as raised: compose_education_entry((identity, date_claim))
        assert raised.value.code is SectionCompositionErrorCode.LINEAGE_MISMATCH
    first, second = compose_education_entry((identity,)), compose_education_entry((identity, date_same))
    with pytest.raises(SectionCompositionError) as raised: compose_education_section((first, second))
    assert raised.value.code is SectionCompositionErrorCode.DUPLICATE_CLAIM


def test_order_and_identity_ids_are_deterministic(generation_context):
    work_a = compose_work_entry((make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_IDENTITY),))
    work_b = compose_work_entry((make_work_rendered_claim(generation_context, "R2", "C1", ClaimRenderingMode.WORK_IDENTITY),))
    forward, reverse = compose_work_section((work_a, work_b)), compose_work_section((work_b, work_a))
    assert forward.entries == (work_a, work_b) and reverse.entries == (work_b, work_a)
    assert forward.section_id != reverse.section_id
    assert compose_work_entry((make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_IDENTITY),)).entry_id == work_a.entry_id
    edu_a = compose_education_entry((make_education_rendered_claim(generation_context, "E1", "C1", ClaimRenderingMode.EDUCATION_IDENTITY),))
    edu_b = compose_education_entry((make_education_rendered_claim(generation_context, "E2", "C1", ClaimRenderingMode.EDUCATION_IDENTITY),))
    assert compose_education_section((edu_a, edu_b)).entries == (edu_a, edu_b)
    assert compose_education_section((edu_a, edu_b)).section_id != compose_education_section((edu_b, edu_a)).section_id


def test_composed_section_schema_enforces_concrete_entry_type(generation_context):
    work = compose_work_entry((make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_IDENTITY),))
    education = compose_education_entry((make_education_rendered_claim(generation_context, "E1", "C1", ClaimRenderingMode.EDUCATION_IDENTITY),))
    valid = ComposedSection(section_id=section_id(SectionType.WORK_EXPERIENCE, (work.entry_id,)), section_type=SectionType.WORK_EXPERIENCE, entries=(work,))
    assert ComposedSection.model_validate(valid.model_dump(mode="json")) == valid
    with pytest.raises(Exception):
        ComposedSection(section_id=section_id(SectionType.WORK_EXPERIENCE, (education.entry_id,)), section_type=SectionType.WORK_EXPERIENCE, entries=(education,))
    with pytest.raises(Exception):
        ComposedSection(section_id=section_id(SectionType.EDUCATION, (work.entry_id,)), section_type=SectionType.EDUCATION, entries=(work,))


def test_direct_entry_schema_reconstruction_invariants(generation_context):
    work = compose_work_entry((make_work_rendered_claim(generation_context, "R1", "C1", ClaimRenderingMode.WORK_IDENTITY),))
    education = compose_education_entry((make_education_rendered_claim(generation_context, "E1", "C1", ClaimRenderingMode.EDUCATION_IDENTITY),))
    assert type(work).model_validate(work.model_dump(mode="json")) == work
    assert type(education).model_validate(education.model_dump(mode="json")) == education
    for entry, replacement in ((work, education.identity_claim), (education, work.identity_claim)):
        payload = entry.model_dump(mode="json")
        payload["identity_claim"] = replacement.model_dump(mode="json")
        with pytest.raises(Exception): type(entry).model_validate(payload)


@pytest.mark.parametrize("mode", [ClaimRenderingMode.ATOMIC_EXACT, ClaimRenderingMode.CONTACT_EXACT])
def test_non_structured_modes_never_enter_work_or_education_entries(generation_context, mode):
    if mode is ClaimRenderingMode.ATOMIC_EXACT:
        from app.services.claim_validation import AtomicClaimAssertion
        assertion = AtomicClaimAssertion(evidence_id=generation_context.atomic_claims[0].evidence_id, claim_type="skill", value="SAP")
    else:
        from app.services.claim_validation import ContactFieldAssertion
        value = generation_context.contact.email
        assertion = ContactFieldAssertion(evidence_id=value.evidence_id, field_name="email", value=value.value.value)
    claim = render_validated_claim(generation_context, proposal("x", ClaimKind.OTHER, assertion), mode)
    for compose, identity in ((compose_work_entry, work_claims(generation_context)[0]), (compose_education_entry, education_claims(generation_context))):
        with pytest.raises(SectionCompositionError) as raised:
            compose((identity, claim))
        assert raised.value.code is SectionCompositionErrorCode.UNEXPECTED_RENDERING_MODE


def test_work_entry_and_section_are_lineage_safe(generation_context):
    identity, date = work_claims(generation_context)
    entry = compose_work_entry((identity, date))
    assert entry.record_id == identity.structured_lineage.record_id
    section = compose_work_section((entry,))
    assert section.entries == (entry,)
    assert section.supporting_evidence_ids if hasattr(section, "supporting_evidence_ids") else True


def test_missing_identity_duplicate_claim_and_wrong_mode_fail_closed(generation_context):
    identity, date = work_claims(generation_context)
    with pytest.raises(SectionCompositionError) as raised:
        compose_work_entry((date,))
    assert raised.value.code is SectionCompositionErrorCode.MISSING_IDENTITY
    with pytest.raises(SectionCompositionError) as raised:
        compose_work_entry((identity, identity))
    assert raised.value.code is SectionCompositionErrorCode.DUPLICATE_SLOT
    with pytest.raises(SectionCompositionError) as raised:
        compose_work_section((compose_work_entry((identity,)), compose_work_entry((identity,))))
    assert raised.value.code is SectionCompositionErrorCode.DUPLICATE_ENTRY


def test_lineage_is_id_bound_and_atomic_has_none(generation_context):
    identity, _ = work_claims(generation_context)
    assert identity.structured_lineage.record_type == "work"
    payload = identity.model_dump(mode="json")
    for field, value in (("record_type", "education"), ("record_id", "other"), ("candidate_id", "other")):
        changed = {**payload, "structured_lineage": {**payload["structured_lineage"], field: value}}
        with pytest.raises(Exception):
            RenderedClaim.model_validate(changed)
    atomic = AtomicClaimAssertion(evidence_id=generation_context.atomic_claims[0].evidence_id, claim_type="skill", value="SAP")
    rendered_atomic = render_validated_claim(generation_context, proposal("SAP", ClaimKind.SKILL, atomic), ClaimRenderingMode.ATOMIC_EXACT)
    assert rendered_atomic.structured_lineage is None
    with pytest.raises(SectionCompositionError) as raised:
        compose_work_entry((identity, rendered_atomic))
    assert raised.value.code is SectionCompositionErrorCode.UNEXPECTED_RENDERING_MODE


def test_empty_sections_reversed_order_and_mutation_are_deterministic(generation_context):
    identity, date = work_claims(generation_context)
    first = compose_work_entry((identity,))
    second = compose_work_entry((identity, date))
    # Shared identity is rejected before it can create ambiguous composition.
    with pytest.raises(SectionCompositionError):
        compose_work_section(())
    before = first.model_dump(mode="json")
    assert compose_work_section((first,)).entries == (first,)
    assert first.model_dump(mode="json") == before


def test_education_identity_modes_and_empty_section_fail_closed(generation_context):
    identity = education_claims(generation_context)
    assert compose_education_entry((identity,)).record_id == identity.structured_lineage.record_id
    with pytest.raises(SectionCompositionError) as raised:
        compose_education_entry(())
    assert raised.value.code is SectionCompositionErrorCode.MISSING_IDENTITY
    with pytest.raises(SectionCompositionError) as raised:
        compose_education_section(())
    assert raised.value.code is SectionCompositionErrorCode.SECTION_TYPE_MISMATCH
    _, work_date = work_claims(generation_context)
    with pytest.raises(SectionCompositionError) as raised:
        compose_education_entry((identity, work_date))
    assert raised.value.code is SectionCompositionErrorCode.UNEXPECTED_RENDERING_MODE


def test_section_type_and_serialized_state_are_strict(generation_context):
    work_entry = compose_work_entry((work_claims(generation_context)[0],))
    education_entry = compose_education_entry((education_claims(generation_context),))
    with pytest.raises(SectionCompositionError) as raised:
        compose_work_section((education_entry,))
    assert raised.value.code is SectionCompositionErrorCode.SECTION_TYPE_MISMATCH
    with pytest.raises(SectionCompositionError) as raised:
        compose_education_section((work_entry,))
    assert raised.value.code is SectionCompositionErrorCode.SECTION_TYPE_MISMATCH
    dumped = compose_work_section((work_entry,)).model_dump(mode="json")
    assert "supporting_evidence_ids" not in dumped
    assert set(dumped) == {"section_id", "section_type", "entries"}

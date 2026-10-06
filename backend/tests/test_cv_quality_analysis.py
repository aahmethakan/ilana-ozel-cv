from datetime import date
import inspect

from app.domain.career import CareerFact, CareerProfile, FactSource, SourceType, VerificationStatus, WorkExperience
from app.domain.document import BlockType, CVDocument, CVSection, DocumentBlock, DocumentFormat, DocumentPage, DocumentSource, SectionType, SourceLocation
from app.extraction.career.result import UnresolvedEvidence
from app.services.cv_quality_analysis import CVQualityDimension, analyze_cv_quality
from app.services.cv_quality_analysis import service as quality_service


def source(reference: str = "page:1:block:1") -> FactSource:
    return FactSource(source_type=SourceType.MASTER_CV, reference=reference, original_text="Synthetic evidence")


def fact(statement: str, *, status: VerificationStatus = VerificationStatus.VERIFIED, skills: tuple[str, ...] = (), tools: tuple[str, ...] = (), metrics: tuple[dict[str, object], ...] = ()) -> CareerFact:
    return CareerFact(statement=statement, verification_status=status, source=source(), skills=skills, tools=tools, metrics=metrics)


def experience(facts: tuple[CareerFact, ...] = ()) -> WorkExperience:
    return WorkExperience(company="Example Works", title="Systems Engineer", start_date=date(2022, 1, 1), end_date=date(2024, 1, 1), facts=facts)


def document() -> CVDocument:
    blocks = (
        DocumentBlock(raw_text="Experience", block_type=BlockType.HEADING, location=SourceLocation(page_number=1, block_index=1)),
        DocumentBlock(raw_text="Improved a synthetic process", block_type=BlockType.BULLET, location=SourceLocation(page_number=1, block_index=2)),
    )
    return CVDocument(
        source=DocumentSource(filename="synthetic.pdf", document_format=DocumentFormat.PDF, page_count=1),
        blocks=blocks,
        pages=(DocumentPage(page_number=1, block_references=tuple(block.stable_reference for block in blocks)),),
        sections=(CVSection(section_type=SectionType.EXPERIENCE, original_heading="Experience", block_references=tuple(block.stable_reference for block in blocks)),),
    )


def empty_document() -> CVDocument:
    return CVDocument(source=DocumentSource(filename="empty.pdf", document_format=DocumentFormat.PDF))


def repeated_bullet_document() -> CVDocument:
    blocks = (
        DocumentBlock(raw_text="Experience", block_type=BlockType.HEADING, location=SourceLocation(page_number=1, block_index=1)),
        DocumentBlock(raw_text="Repeated synthetic bullet", block_type=BlockType.BULLET, location=SourceLocation(page_number=1, block_index=2)),
        DocumentBlock(raw_text="Repeated synthetic bullet", block_type=BlockType.BULLET, location=SourceLocation(page_number=1, block_index=3)),
    )
    return CVDocument(
        source=DocumentSource(filename="repeated.pdf", document_format=DocumentFormat.PDF, page_count=1),
        blocks=blocks,
        pages=(DocumentPage(page_number=1, block_references=tuple(block.stable_reference for block in blocks)),),
        sections=(CVSection(section_type=SectionType.EXPERIENCE, original_heading="Experience", block_references=tuple(block.stable_reference for block in blocks)),),
    )


def dimension(result, value: CVQualityDimension) -> int:
    return next(item.score for item in result.dimensions if item.dimension is value)


def test_empty_profile_is_low_valid_and_deterministic() -> None:
    first = analyze_cv_quality(CareerProfile())
    second = analyze_cv_quality(CareerProfile())

    assert first == second
    assert 0 <= first.overall_score <= 100
    assert first.overall_score < 50
    assert all(0 <= item.score <= item.max_score for item in first.dimensions)


def test_verified_and_user_provided_facts_count_but_inferred_facts_do_not() -> None:
    verified = CareerProfile(skills=(fact("Excel", skills=("Excel",)),))
    user = CareerProfile(skills=(fact("SAP", status=VerificationStatus.USER_PROVIDED, skills=("SAP",)),))
    inferred = CareerProfile(skills=(fact("Python", status=VerificationStatus.INFERRED_UNVERIFIED, skills=("Python",)),))

    assert dimension(analyze_cv_quality(verified), CVQualityDimension.COMPLETENESS) > dimension(analyze_cv_quality(inferred), CVQualityDimension.COMPLETENESS)
    assert dimension(analyze_cv_quality(user), CVQualityDimension.EVIDENCE) > dimension(analyze_cv_quality(inferred), CVQualityDimension.EVIDENCE)


def test_duplicate_skills_do_not_increase_score_and_distinct_names_remain_distinct() -> None:
    duplicate = CareerProfile(skills=(fact("Excel", skills=("Excel",)), fact(" excel ", skills=(" excel ",))))
    distinct = CareerProfile(skills=(fact("Excel", skills=("Excel",)), fact("Advanced Excel", skills=("Advanced Excel",)), fact("SAP", skills=("SAP",)), fact("SAP ERP", skills=("SAP ERP",))))

    assert analyze_cv_quality(duplicate).overall_score == analyze_cv_quality(CareerProfile(skills=(fact("Excel", skills=("Excel",)),))).overall_score
    assert dimension(analyze_cv_quality(distinct), CVQualityDimension.EVIDENCE) > dimension(analyze_cv_quality(duplicate), CVQualityDimension.EVIDENCE)


def test_explicit_metric_improves_evidence_without_inventing_one() -> None:
    without_metric = CareerProfile(work_experiences=(experience((fact("Improved workflow"),)),))
    with_metric = CareerProfile(work_experiences=(experience((fact("Reduced cycle time by 12%", metrics=({"value": 12, "unit": "%"},)),)),))

    assert dimension(analyze_cv_quality(with_metric), CVQualityDimension.EVIDENCE) > dimension(analyze_cv_quality(without_metric), CVQualityDimension.EVIDENCE)
    assert "explicit_metrics" not in {finding.code for finding in analyze_cv_quality(without_metric).findings}


def test_unresolved_experience_is_distinguished_from_absent_experience() -> None:
    unresolved = (UnresolvedEvidence(block_reference="page:1:block:1", section_type=SectionType.EXPERIENCE, reason="ambiguous_experience_content"),)
    uncertain = analyze_cv_quality(CareerProfile(), unresolved_evidence=unresolved)
    absent = analyze_cv_quality(CareerProfile())

    assert "experience_information_unresolved" in {finding.code for finding in uncertain.findings}
    assert "experience_not_structured" in {finding.code for finding in absent.findings}
    assert dimension(uncertain, CVQualityDimension.COMPLETENESS) > dimension(absent, CVQualityDimension.COMPLETENESS)


def test_structured_and_unresolved_education_receive_distinct_partial_completeness_credit() -> None:
    unresolved = (UnresolvedEvidence(block_reference="page:1:block:2", section_type=SectionType.EDUCATION, reason="ambiguous_education_content"),)
    uncertain = analyze_cv_quality(CareerProfile(), unresolved_evidence=unresolved)
    absent = analyze_cv_quality(CareerProfile())

    assert "education_information_unresolved" in {finding.code for finding in uncertain.findings}
    assert "education_not_structured" in {finding.code for finding in absent.findings}
    assert dimension(uncertain, CVQualityDimension.COMPLETENESS) > dimension(absent, CVQualityDimension.COMPLETENESS)


def test_structured_experience_scores_above_unresolved_experience() -> None:
    unresolved = (UnresolvedEvidence(block_reference="page:1:block:1", section_type=SectionType.EXPERIENCE, reason="ambiguous_experience_content"),)
    structured = analyze_cv_quality(CareerProfile(work_experiences=(experience(),)))
    uncertain = analyze_cv_quality(CareerProfile(), unresolved_evidence=unresolved)

    assert dimension(structured, CVQualityDimension.COMPLETENESS) > dimension(uncertain, CVQualityDimension.COMPLETENESS)


def test_machine_readable_document_and_ambiguity_have_bounded_structure_effects() -> None:
    clear = analyze_cv_quality(CareerProfile(), document=document())
    ambiguous = analyze_cv_quality(CareerProfile(), document=document(), unresolved_evidence=tuple(UnresolvedEvidence(block_reference=f"page:1:block:{index}", section_type=None, reason="ambiguous") for index in range(1, 20)))

    assert 0 < dimension(clear, CVQualityDimension.ATS_READINESS) < 20
    assert dimension(ambiguous, CVQualityDimension.STRUCTURE) == dimension(clear, CVQualityDimension.STRUCTURE) - 3
    assert all(finding.code != "certification_not_present" for finding in clear.findings)


def test_inputs_are_not_mutated_and_findings_are_stable() -> None:
    profile = CareerProfile(work_experiences=(experience((fact("Türkçe araç", tools=("Araç",)),)),))
    source_document = document()

    result = analyze_cv_quality(profile, document=source_document)

    assert profile.work_experiences[0].facts[0].statement == "Türkçe araç"
    assert source_document == document()
    assert result.findings == tuple(sorted(result.findings, key=lambda item: (item.dimension.value, item.code, item.evidence_references)))


def test_document_unavailable_is_explicit_and_cannot_improve_the_score() -> None:
    profile = CareerProfile()
    unavailable = analyze_cv_quality(profile)
    weak_known_document = analyze_cv_quality(profile, document=empty_document())

    structure = next(item for item in unavailable.dimensions if item.dimension is CVQualityDimension.STRUCTURE)
    ats = next(item for item in unavailable.dimensions if item.dimension is CVQualityDimension.ATS_READINESS)
    assert structure.is_evaluated is False and structure.score == 0
    assert ats.is_evaluated is False and ats.score == 0
    assert unavailable.overall_score <= weak_known_document.overall_score
    assert {"document_structure_not_evaluated", "ats_readiness_not_evaluated"} <= {finding.code for finding in unavailable.findings}


def test_inferred_experience_metrics_do_not_improve_evidence_or_create_strengths() -> None:
    inferred = CareerProfile(work_experiences=(experience((fact("Reduced synthetic time by 12%", status=VerificationStatus.INFERRED_UNVERIFIED, metrics=({"value": 12, "unit": "%"},)),)),))
    baseline = CareerProfile(work_experiences=(experience(),))

    result = analyze_cv_quality(inferred)

    assert dimension(result, CVQualityDimension.EVIDENCE) == dimension(analyze_cv_quality(baseline), CVQualityDimension.EVIDENCE)
    assert "explicit_metrics" not in {finding.code for finding in result.strengths}


def test_every_evaluated_material_deduction_has_a_negative_finding_code() -> None:
    result = analyze_cv_quality(CareerProfile(), document=empty_document())

    for item in result.dimensions:
        if item.is_evaluated and item.score < item.max_score:
            assert any(finding.dimension is item.dimension and finding.score_impact < 0 for finding in result.findings)


def test_repeated_identical_bullets_do_not_inflate_structure_or_ats_scores() -> None:
    single = analyze_cv_quality(CareerProfile(), document=document())
    repeated = analyze_cv_quality(CareerProfile(), document=repeated_bullet_document())

    assert dimension(single, CVQualityDimension.STRUCTURE) == dimension(repeated, CVQualityDimension.STRUCTURE)
    assert dimension(single, CVQualityDimension.ATS_READINESS) == dimension(repeated, CVQualityDimension.ATS_READINESS)


def test_quality_service_has_no_ai_dependency_or_fact_creation() -> None:
    source_text = inspect.getsource(quality_service)
    assert "app.ai" not in source_text
    assert "CareerFact(" not in source_text

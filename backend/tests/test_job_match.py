import inspect

import pytest
from pydantic import ValidationError

from app.confirmation.career import ConfirmationAction, resolve_candidate
from app.domain.career import (
    CareerFact,
    CareerProfile,
    Certification,
    FactSource,
    LanguageSkill,
    SourceType,
    VerificationStatus,
)
from app.domain.job import (
    JobProfile,
    JobRequirement,
    RequirementCategory,
    RequirementExplicitness,
    RequirementImportance,
)
from app.services.job_analysis import UnresolvedJobItem
from app.services.career_gap_analysis import CoachQuestion, GapCategory, GapPriority
from app.services.career_gap_analysis.schemas import AnswerType
from app.services.coach_answer_processing import CoachAnswer, process_coach_answer
from app.services.job_match import RequirementMatchStatus, RequirementMatchType, match_job_to_profile
from app.services.job_match import service as match_service


def source(reference: str | None = "cv:synthetic:1", source_type: SourceType = SourceType.MASTER_CV) -> FactSource:
    return FactSource(source_type=source_type, reference=reference, original_text="synthetic evidence")


def skill(name: str, status: VerificationStatus = VerificationStatus.VERIFIED, reference: str | None = "cv:skill:1") -> CareerFact:
    return CareerFact(statement=name, skills=(name,), verification_status=status, source=source(reference))


def requirement(
    text: str,
    category: RequirementCategory = RequirementCategory.SKILL,
    importance: RequirementImportance = RequirementImportance.REQUIRED,
    reference: str = "job:line:1",
) -> JobRequirement:
    return JobRequirement(
        requirement_id=f"synthetic:{category.value}:{text}",
        category=category,
        text=text,
        importance=importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source_references=(reference,),
        source_texts=(text,),
    )


def match(requirements: tuple[JobRequirement, ...], profile: CareerProfile) -> tuple:
    return match_job_to_profile(JobProfile(requirements=requirements), profile).requirement_results


@pytest.mark.parametrize(
    ("job_name", "career_name", "expected"),
    [
        ("SAP", "SAP", RequirementMatchStatus.MATCHED),
        ("SAP ERP", "SAP", RequirementMatchStatus.NOT_EVIDENCED),
        ("Excel", "Advanced Excel", RequirementMatchStatus.NOT_EVIDENCED),
        ("PLC", "Siemens PLC", RequirementMatchStatus.NOT_EVIDENCED),
        ("CATIA", "CATIA", RequirementMatchStatus.MATCHED),
    ],
)
def test_skill_matching_is_exact_only(job_name: str, career_name: str, expected: RequirementMatchStatus) -> None:
    result = match((requirement(job_name),), CareerProfile(skills=(skill(career_name),)))[0]

    assert result.status is expected
    assert result.matched_evidence_references == (("cv:skill:1",) if expected is RequirementMatchStatus.MATCHED else ())


def test_verified_and_user_provided_skills_can_match_but_inferred_skill_cannot() -> None:
    target = requirement("SAP")
    assert match((target,), CareerProfile(skills=(skill("SAP", VerificationStatus.VERIFIED),)))[0].status is RequirementMatchStatus.MATCHED
    assert match((target,), CareerProfile(skills=(skill("SAP", VerificationStatus.USER_PROVIDED),)))[0].status is RequirementMatchStatus.MATCHED
    inferred = match((target,), CareerProfile(skills=(skill("SAP", VerificationStatus.INFERRED_UNVERIFIED),)))[0]
    assert inferred.status is RequirementMatchStatus.NOT_EVIDENCED
    assert inferred.matched_evidence_references == ()


def test_tool_requirements_match_only_explicit_trusted_tool_evidence() -> None:
    tool_fact = CareerFact(
        statement="SAP",
        tools=("SAP",),
        verification_status=VerificationStatus.VERIFIED,
        source=source("cv:tool:1"),
    )
    result = match((requirement("SAP", RequirementCategory.TOOL),), CareerProfile(tools=(tool_fact,)))[0]

    assert result.status is RequirementMatchStatus.MATCHED
    assert result.matched_evidence_references == ("cv:tool:1",)


def test_tool_and_skill_categories_do_not_cross_match() -> None:
    skill_only = skill("SAP", reference="cv:skill:1")
    tool_only = CareerFact(statement="SAP", tools=("SAP",), verification_status=VerificationStatus.VERIFIED, source=source("cv:tool:1"))

    assert match((requirement("SAP", RequirementCategory.TOOL),), CareerProfile(skills=(skill_only,)))[0].status is RequirementMatchStatus.NOT_EVIDENCED
    assert match((requirement("SAP", RequirementCategory.SKILL),), CareerProfile(tools=(tool_only,)))[0].status is RequirementMatchStatus.NOT_EVIDENCED


def test_generic_requirement_matches_only_exact_trusted_named_profile_evidence() -> None:
    generic = requirement("SQL", RequirementCategory.OTHER)
    exact = match((generic,), CareerProfile(skills=(skill("SQL"),)))[0]
    inferred = match((generic,), CareerProfile(skills=(skill("SQL", VerificationStatus.INFERRED_UNVERIFIED),)))[0]
    expanded = match((generic,), CareerProfile(skills=(skill("SQL Server"),)))[0]

    assert exact.status is RequirementMatchStatus.MATCHED
    assert exact.matched_evidence_references == ("cv:skill:1",)
    assert inferred.status is RequirementMatchStatus.NOT_EVALUABLE
    assert expanded.status is RequirementMatchStatus.NOT_EVALUABLE


def test_importance_is_preserved_and_aggregated_without_treating_unknown_as_required() -> None:
    requirements = (
        requirement("SAP", importance=RequirementImportance.REQUIRED),
        requirement("Excel", importance=RequirementImportance.PREFERRED, reference="job:line:2"),
        requirement("CATIA", importance=RequirementImportance.UNKNOWN, reference="job:line:3"),
    )
    result = match_job_to_profile(JobProfile(requirements=requirements), CareerProfile(skills=(skill("SAP"),)))

    assert [item.requirement.importance for item in result.requirement_results] == [RequirementImportance.REQUIRED, RequirementImportance.PREFERRED, RequirementImportance.UNKNOWN]
    assert result.matched_required_count == 1
    assert result.not_evidenced_preferred_count == 1
    assert result.not_evidenced_required_count == 0


def test_language_matching_requires_exact_language_and_explicit_proficiency() -> None:
    profile = CareerProfile(languages=(LanguageSkill(language="English", proficiency="B2", source=source("cv:language:1")),))
    results = match(
        (
            requirement("English", RequirementCategory.LANGUAGE),
            requirement("English B2", RequirementCategory.LANGUAGE, reference="job:line:2"),
            requirement("English C1", RequirementCategory.LANGUAGE, reference="job:line:3"),
        ),
        profile,
    )

    assert [item.status for item in results] == [RequirementMatchStatus.MATCHED, RequirementMatchStatus.MATCHED, RequirementMatchStatus.PARTIAL]
    assert all(item.matched_evidence_references == ("cv:language:1",) for item in results)
    assert results[2].reason_code == "language_identity_matched_proficiency_not_evidenced"
    assert results[2].explanation == "Explicit language identity is evidenced, but the required proficiency is not evidenced."


def test_language_without_safe_structure_is_not_evaluable_and_no_fluent_to_cefr_inference() -> None:
    profile = CareerProfile(languages=(LanguageSkill(language="English", proficiency="Fluent", source=source("cv:language:1")),))
    result = match((requirement("Fluent English", RequirementCategory.LANGUAGE),), profile)[0]

    assert result.status is RequirementMatchStatus.NOT_EVALUABLE
    assert result.matched_evidence_references == ()


def test_certifications_match_exactly_and_only_when_trusted() -> None:
    pmp = Certification(name="PMP", source=source("cv:cert:1"))
    training = Certification(name="Project Management training", source=source("cv:cert:2"))
    profile = CareerProfile(certifications=(pmp, training))
    results = match(
        (
            requirement("PMP", RequirementCategory.CERTIFICATION),
            requirement("Project Management Professional", RequirementCategory.CERTIFICATION, reference="job:line:2"),
        ),
        profile,
    )

    assert [item.status for item in results] == [RequirementMatchStatus.MATCHED, RequirementMatchStatus.NOT_EVIDENCED]
    assert results[0].matched_evidence_references == ("cv:cert:1",)


def test_untrusted_language_and_certification_cannot_match() -> None:
    untrusted_source = source("inference:1", SourceType.SYSTEM_INFERENCE)
    profile = CareerProfile(
        languages=(LanguageSkill(language="English", proficiency="B2", source=untrusted_source),),
        certifications=(Certification(name="PMP", source=untrusted_source),),
    )
    results = match(
        (requirement("English", RequirementCategory.LANGUAGE), requirement("PMP", RequirementCategory.CERTIFICATION)),
        profile,
    )

    assert [item.status for item in results] == [RequirementMatchStatus.NOT_EVIDENCED, RequirementMatchStatus.NOT_EVIDENCED]


@pytest.mark.parametrize("category", [RequirementCategory.EDUCATION, RequirementCategory.EXPERIENCE, RequirementCategory.OTHER])
def test_unsafe_categories_are_not_turned_into_false_mismatches(category: RequirementCategory) -> None:
    result = match((requirement("Synthetic requirement", category),), CareerProfile())[0]

    assert result.status is RequirementMatchStatus.NOT_EVALUABLE
    assert result.matched_evidence_references == ()


def test_responsibilities_are_not_matched_and_unresolved_job_items_are_preserved() -> None:
    unresolved = UnresolvedJobItem(source_reference="job:line:9", original_text="Synthetic prose", reason_code="unknown_section")
    profile = JobProfile(
        responsibilities=(requirement("Manage schedules", RequirementCategory.RESPONSIBILITY),),
        requirements=(requirement("SAP"),),
    )
    result = match_job_to_profile(profile, CareerProfile(skills=(skill("SAP"),)), unresolved_job_items=(unresolved,))

    assert len(result.requirement_results) == 1
    assert result.requirement_results[0].requirement.text == "SAP"
    assert result.unresolved_job_items == (unresolved,)


def test_duplicate_malformed_requirements_do_not_inflate_aggregates_or_mutate_inputs() -> None:
    first = requirement("SAP", reference="job:line:1")
    duplicate = requirement(" sap ", reference="job:line:2")
    profile = JobProfile(requirements=(first, duplicate))
    career = CareerProfile(skills=(skill("SAP"),))
    result = match_job_to_profile(profile, career)

    assert len(result.requirement_results) == 1
    assert result.matched_required_count == 1
    assert profile.requirements == (first, duplicate)
    assert career.skills[0].statement == "SAP"


def test_malformed_duplicate_with_conflicting_importance_remains_unknown_and_uncounted() -> None:
    required = requirement("SAP", importance=RequirementImportance.REQUIRED)
    preferred = requirement(" sap ", importance=RequirementImportance.PREFERRED, reference="job:line:2")
    result = match_job_to_profile(JobProfile(requirements=(required, preferred)), CareerProfile(skills=(skill("SAP"),)))

    assert result.requirement_results[0].requirement.importance is RequirementImportance.UNKNOWN
    assert result.requirement_results[0].requirement.source_references == ("job:line:1", "job:line:2")
    assert result.matched_required_count == result.matched_preferred_count == 0


def test_confirmed_coach_answer_with_user_input_provenance_can_match() -> None:
    question = CoachQuestion(
        question_id="tool-question",
        category=GapCategory.TOOL,
        question_text="Synthetic tool question",
        reason="Synthetic evidence gap.",
        target_section="skills",
        priority=GapPriority.MEDIUM,
        evidence_references=(),
        missing_signal="synthetic_tool",
        answer_type=AnswerType.YES_NO_DETAILS,
    )
    answer_result = process_coach_answer(question, CoachAnswer(question_id="tool-question", answer_text="SAP"))
    assert answer_result.candidate is not None
    resolution = resolve_candidate(answer_result.candidate, ConfirmationAction.ACCEPT)
    assert resolution.promoted_fact is not None

    result = match(
        (requirement("SAP", RequirementCategory.TOOL),),
        CareerProfile(tools=(resolution.promoted_fact,)),
    )[0]

    assert result.status is RequirementMatchStatus.MATCHED
    assert result.matched_evidence_references == ("coach_question:tool-question",)


def test_unreferenced_trusted_evidence_is_not_reported_as_a_match() -> None:
    result = match((requirement("SAP"),), CareerProfile(skills=(skill("SAP", reference=None),)))[0]

    assert result.status is RequirementMatchStatus.NOT_EVALUABLE
    assert result.matched_evidence_references == ()


def test_results_are_immutable_deterministic_and_have_no_ai_or_score_dependency() -> None:
    job = JobProfile(requirements=(requirement("SAP"),))
    career = CareerProfile(skills=(skill("SAP"),))
    first = match_job_to_profile(job, career)
    second = match_job_to_profile(job, career)

    assert first == second
    with pytest.raises(ValidationError):
        first.matched_required_count = 99
    source_text = inspect.getsource(match_service)
    assert "app.ai" not in source_text
    assert "embedding" not in source_text
    assert "score" not in source_text.casefold()


@pytest.mark.parametrize(
    ("candidate", "job", "expected_status", "expected_type"),
    [
        ("Excel", "Excel", RequirementMatchStatus.MATCHED, RequirementMatchType.EXACT),
        ("excel", "Excel", RequirementMatchStatus.MATCHED, RequirementMatchType.NORMALIZED_EXACT),
        ("S&OP", "Sales and Operations Planning", RequirementMatchStatus.MATCHED, RequirementMatchType.CONTROLLED_SEMANTIC),
        ("ERP", "SAP ERP", RequirementMatchStatus.PARTIAL, RequirementMatchType.PARTIAL),
        ("PLC", "PLC programming", RequirementMatchStatus.NOT_EVIDENCED, RequirementMatchType.UNMATCHED),
        ("data analysis", "Python", RequirementMatchStatus.NOT_EVIDENCED, RequirementMatchType.UNMATCHED),
    ],
)
def test_conservative_skill_normalization_and_semantic_boundaries(candidate, job, expected_status, expected_type) -> None:
    result = match((requirement(job),), CareerProfile(skills=(skill(candidate),)))[0]

    assert result.status is expected_status
    assert result.match_type is expected_type
    if expected_status is RequirementMatchStatus.MATCHED:
        assert result.matched_evidence_references == ("cv:skill:1",)


def test_tool_technology_boundary_allows_only_controlled_synonyms() -> None:
    excel = CareerFact(statement="Microsoft Excel", tools=("Microsoft Excel",), verification_status=VerificationStatus.VERIFIED, source=source("cv:tool:excel"))
    erp = CareerFact(statement="ERP", tools=("ERP",), verification_status=VerificationStatus.VERIFIED, source=source("cv:tool:erp"))
    plc = CareerFact(statement="PLC programming", tools=("PLC programming",), verification_status=VerificationStatus.VERIFIED, source=source("cv:tool:plc"))
    results = match((requirement("MS Excel", RequirementCategory.TOOL), requirement("SAP ERP", RequirementCategory.TOOL), requirement("Siemens PLC", RequirementCategory.TOOL)), CareerProfile(tools=(excel, erp, plc)))

    assert [item.status for item in results] == [RequirementMatchStatus.MATCHED, RequirementMatchStatus.NOT_EVIDENCED, RequirementMatchStatus.NOT_EVIDENCED]
    assert results[0].match_type is RequirementMatchType.CONTROLLED_SEMANTIC
    assert all(item.matched_evidence_references == () for item in results[1:])


def test_controlled_certification_and_language_equivalences_remain_evidence_backed() -> None:
    profile = CareerProfile(certifications=(Certification(name="PMP", source=source("cv:cert:pmp")),), languages=(LanguageSkill(language="English", proficiency="C1", source=source("cv:language:english")),))
    results = match((requirement("PMP certification", RequirementCategory.CERTIFICATION), requirement("Advanced English", RequirementCategory.LANGUAGE)), profile)

    assert [item.status for item in results] == [RequirementMatchStatus.MATCHED, RequirementMatchStatus.MATCHED]
    assert all(item.match_type is RequirementMatchType.CONTROLLED_SEMANTIC for item in results)
    assert [item.matched_evidence_references for item in results] == [("cv:cert:pmp",), ("cv:language:english",)]


def test_inferred_and_job_only_values_never_become_semantic_evidence() -> None:
    profile = CareerProfile(skills=(skill("SAP", VerificationStatus.INFERRED_UNVERIFIED),))
    result = match((requirement("SAP"), requirement("Siemens PLC")), profile)

    assert all(item.status is RequirementMatchStatus.NOT_EVIDENCED for item in result)
    assert all(item.match_type is RequirementMatchType.UNMATCHED for item in result)
    assert "Siemens" not in profile.model_dump_json()

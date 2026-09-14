from datetime import date
import inspect

from app.domain.career import (
    CareerFact,
    CareerProfile,
    Certification,
    FactSource,
    LanguageSkill,
    SourceType,
    VerificationStatus,
    WorkExperience,
)
from app.services.career_gap_analysis import GapAnalysisContext, GapCategory, analyze_career_profile_gaps
from app.services.career_gap_analysis import service as gap_service


def source(reference: str = "page:1:block:1") -> FactSource:
    return FactSource(source_type=SourceType.MASTER_CV, reference=reference, original_text="Synthetic evidence")


def fact(
    statement: str,
    *,
    status: VerificationStatus = VerificationStatus.VERIFIED,
    skills: tuple[str, ...] = (),
    tools: tuple[str, ...] = (),
    metrics: tuple[dict[str, object], ...] = (),
) -> CareerFact:
    return CareerFact(statement=statement, verification_status=status, source=source(), skills=skills, tools=tools, metrics=metrics)


def experience(title: str = "Systems Engineer", facts: tuple[CareerFact, ...] = ()) -> WorkExperience:
    return WorkExperience(company="Example Works", title=title, start_date=date(2022, 1, 1), end_date=date(2024, 1, 1), facts=facts)


def categories(result) -> set[GapCategory]:
    return {question.category for question in result.questions}


def test_empty_profile_has_only_safe_global_questions() -> None:
    result = analyze_career_profile_gaps(CareerProfile())

    assert categories(result) == {GapCategory.CERTIFICATION, GapCategory.LANGUAGE}
    assert all("not currently" in question.question_text or "not currently" in question.reason for question in result.questions)


def test_existing_certification_and_language_suppress_their_global_questions() -> None:
    profile = CareerProfile(
        certifications=(Certification(name="Synthetic Certification", source=source()),),
        languages=(LanguageSkill(language="Turkish", proficiency="Native", source=source()),),
    )

    assert categories(analyze_career_profile_gaps(profile)) == set()


def test_experience_without_metrics_or_tools_gets_role_aware_questions_with_only_real_refs() -> None:
    role_fact = fact("Designed a production workflow")
    profile = CareerProfile(work_experiences=(experience("Process Engineer", (role_fact,)),))

    result = analyze_career_profile_gaps(profile)

    assert {GapCategory.METRIC, GapCategory.TOOL} <= categories(result)
    role_questions = [question for question in result.questions if question.related_role == "Process Engineer"]
    assert all(question.evidence_references == ("page:1:block:1",) for question in role_questions)
    assert GapCategory.LEADERSHIP not in categories(result)
    assert GapCategory.PROJECT_MANAGEMENT not in categories(result)


def test_existing_trusted_metric_and_tool_evidence_suppresses_equivalent_gaps() -> None:
    trusted = fact("Improved workflow", skills=("Python",), metrics=({"value": 20, "unit": "%"},))
    profile = CareerProfile(work_experiences=(experience(facts=(trusted,)),))

    result = analyze_career_profile_gaps(profile)

    assert GapCategory.METRIC not in categories(result)
    assert GapCategory.TOOL not in categories(result)


def test_untrusted_fact_does_not_suppress_a_gap() -> None:
    inferred = fact("Improved workflow", status=VerificationStatus.INFERRED_UNVERIFIED, tools=("Synthetic Tool",), metrics=({"value": 20},))
    profile = CareerProfile(work_experiences=(experience(facts=(inferred,)),))

    result = analyze_career_profile_gaps(profile)

    assert {GapCategory.METRIC, GapCategory.TOOL} <= categories(result)


def test_leadership_and_project_questions_require_role_or_context_relevance() -> None:
    junior = analyze_career_profile_gaps(CareerProfile(work_experiences=(experience("Junior Engineer"),)))
    relevant = analyze_career_profile_gaps(CareerProfile(work_experiences=(experience("Engineering Manager"),)))

    assert GapCategory.LEADERSHIP not in categories(junior)
    assert GapCategory.PROJECT_MANAGEMENT not in categories(junior)
    assert {GapCategory.LEADERSHIP, GapCategory.PROJECT_MANAGEMENT} <= categories(relevant)


def test_specialized_plc_and_erp_questions_are_never_universally_generated() -> None:
    result = analyze_career_profile_gaps(CareerProfile(work_experiences=(experience("Software Developer"),)))

    rendered = " ".join(question.question_text.casefold() for question in result.questions)
    assert "plc" not in rendered
    assert "sap" not in rendered
    assert "erp" not in rendered


def test_ids_results_and_cap_are_deterministic_and_prioritized() -> None:
    profile = CareerProfile(work_experiences=(experience("Engineering Manager"),))
    context = GapAnalysisContext(max_questions=1)

    first = analyze_career_profile_gaps(profile, context)
    second = analyze_career_profile_gaps(profile, context)

    assert first == second
    assert len(first.questions) == 1
    assert first.questions[0].category is GapCategory.METRIC
    assert len({question.question_id for question in analyze_career_profile_gaps(profile).questions}) == len(analyze_career_profile_gaps(profile).questions)


def test_questions_do_not_mutate_or_create_facts() -> None:
    original_fact = fact("Used a synthetic tool", status=VerificationStatus.USER_PROVIDED, tools=("Synthetic Tool",))
    profile = CareerProfile(work_experiences=(experience(facts=(original_fact,)),))

    result = analyze_career_profile_gaps(profile)

    assert profile.work_experiences[0].facts == (original_fact,)
    assert GapCategory.TOOL not in categories(result)
    assert all(not isinstance(question, CareerFact) for question in result.questions)


def test_duplicate_role_policies_are_deduplicated_and_unicode_is_stable() -> None:
    profile = CareerProfile(
        work_experiences=(experience("Üretim Mühendisi"), experience("Üretim Mühendisi"))
    )

    result = analyze_career_profile_gaps(profile)

    role_questions = [question for question in result.questions if question.related_role == "Üretim Mühendisi"]
    assert len(role_questions) == 2
    assert len({question.question_id for question in role_questions}) == 2


def test_gap_analysis_service_has_no_ai_provider_dependency() -> None:
    assert "app.ai" not in inspect.getsource(gap_service)

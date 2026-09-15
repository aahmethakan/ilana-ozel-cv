import inspect

import pytest
from pydantic import ValidationError

from app.domain.job import JobDocument, JobSourceType, RequirementCategory, RequirementImportance
from app.services.job_analysis import analyze_job_description
from app.services.job_analysis import service as job_service


def analyze(text: str, **kwargs):
    return analyze_job_description(JobDocument(raw_text=text, **kwargs))


def test_raw_text_hints_and_results_are_immutable_and_deterministic() -> None:
    text = "Requirements\n- SAP\n"
    document = JobDocument(raw_text=text, title_hint="Systems Engineer", company_hint="Example Works", source_reference="user:paste:1")
    first = analyze_job_description(document)
    second = analyze_job_description(document)

    assert document.raw_text == text
    assert document.source_type is JobSourceType.PASTED_TEXT
    assert first == second
    assert first.profile.title == "Systems Engineer"
    assert first.profile.company == "Example Works"
    with pytest.raises(ValidationError):
        document.raw_text = "changed"
    with pytest.raises(ValidationError):
        first.profile.title = "changed"


def test_explicit_labeled_title_and_company_are_extracted_without_guessing() -> None:
    result = analyze("Job Title: Production Engineer\nCompany: Example Manufacturing\nRequirements\n- SAP")

    assert result.profile.title == "Production Engineer"
    assert result.profile.company == "Example Manufacturing"


def test_english_and_turkish_sections_preserve_bullets_and_stable_refs() -> None:
    result = analyze("Requirements\n- SAP\nPreferred Qualifications\n- Excel\nSorumluluklar\n- Installation schedule coordination\nAranan Nitelikler\n- PLC")

    assert {(item.text, item.importance) for item in result.profile.requirements} == {("SAP", RequirementImportance.REQUIRED), ("Excel", RequirementImportance.PREFERRED), ("PLC", RequirementImportance.REQUIRED)}
    assert result.profile.responsibilities[0].text == "Installation schedule coordination"
    assert result.profile.responsibilities[0].source_texts == ("- Installation schedule coordination",)
    assert {reference for item in result.profile.requirements for reference in item.source_references} == {"job:line:2", "job:line:4", "job:line:8"}


def test_original_line_numbers_remain_stable_across_blank_lines() -> None:
    raw_text = "Requirements\n\n- SAP\n"
    result = analyze(raw_text)

    assert result.profile.requirements[0].source_references == ("job:line:3",)
    assert JobDocument(raw_text=raw_text).raw_text == raw_text


def test_inline_importance_and_explicit_names_are_not_strengthened() -> None:
    result = analyze("Requirements\n- must have SAP\nPreferred Qualifications\n- preferred Excel\nSkills\n- Advanced Excel\n- Siemens TIA Portal")

    assert {(item.text, item.importance) for item in result.profile.requirements if item.category is RequirementCategory.OTHER} == {("must have SAP", RequirementImportance.REQUIRED), ("preferred Excel", RequirementImportance.PREFERRED)}
    skills = {item.text for item in result.profile.requirements if item.category is RequirementCategory.SKILL}
    assert skills == {"Advanced Excel", "Siemens TIA Portal"}
    assert "SAP ERP" not in skills and "Excel" not in skills


def test_requirement_category_safety_prefers_explicit_categories_or_other() -> None:
    result = analyze(
        "Requirements\n"
        "- 3+ years of manufacturing experience\n"
        "- Bachelor's degree in Mechanical Engineering\n"
        "- Fluent English\n"
        "- Willingness to travel\n"
        "- Experience in commissioning industrial equipment"
    )
    by_text = {item.text: item.category for item in result.profile.requirements}

    assert by_text["3+ years of manufacturing experience"] is RequirementCategory.EXPERIENCE
    assert by_text["Bachelor's degree in Mechanical Engineering"] is RequirementCategory.EDUCATION
    assert by_text["Fluent English"] is RequirementCategory.LANGUAGE
    assert by_text["Willingness to travel"] is RequirementCategory.OTHER
    assert by_text["Experience in commissioning industrial equipment"] is RequirementCategory.OTHER


def test_responsibilities_are_not_converted_to_skills_and_unknown_lines_remain_visible() -> None:
    result = analyze("Responsibilities\n- Manage installation schedules\nAbout the Role\n- Collaborative environment\nWho You Are\n- Able to work under pressure")

    assert result.profile.responsibilities[0].category is RequirementCategory.RESPONSIBILITY
    assert all(item.category is not RequirementCategory.SKILL for item in result.profile.requirements)
    assert {item.original_text for item in result.unresolved_items} == {"- Collaborative environment", "- Able to work under pressure"}


def test_experience_education_language_and_certification_are_preserved_without_inference() -> None:
    result = analyze("Requirements\n- 3+ years of experience\nEducation\n- Bachelor's degree in Mechanical Engineering\nLanguages\n- English B2\nCertifications\n- PMP")
    categories = {item.category: item.text for item in result.profile.requirements}

    assert categories[RequirementCategory.EXPERIENCE] == "3+ years of experience"
    assert categories[RequirementCategory.EDUCATION] == "Bachelor's degree in Mechanical Engineering"
    assert categories[RequirementCategory.LANGUAGE] == "English B2"
    assert categories[RequirementCategory.CERTIFICATION] == "PMP"
    assert "senior" not in " ".join(categories.values()).casefold()
    assert "C1" not in categories[RequirementCategory.LANGUAGE]


def test_exact_duplicate_deduplicates_with_all_refs_and_importance_conflict_is_visible() -> None:
    result = analyze("Requirements\n- SAP\n- SAP\nPreferred Qualifications\n- SAP")

    assert len(result.profile.requirements) == 1
    assert result.profile.requirements[0].importance is RequirementImportance.UNKNOWN
    assert result.profile.requirements[0].source_references == ("job:line:2", "job:line:3", "job:line:5")
    assert result.conflicts[0].importance_values == (RequirementImportance.PREFERRED, RequirementImportance.REQUIRED)
    assert result.conflicts[0].required_source_references == ("job:line:2", "job:line:3")
    assert result.conflicts[0].preferred_source_references == ("job:line:5",)


def test_inline_and_section_importance_contradictions_are_visible() -> None:
    result = analyze("Requirements\n- preferred SAP\nPreferred Qualifications\n- mandatory Excel")

    assert {item.importance for item in result.profile.requirements} == {RequirementImportance.UNKNOWN}
    assert {(item.text, item.importance_values) for item in result.conflicts} == {
        ("preferred SAP", (RequirementImportance.PREFERRED, RequirementImportance.REQUIRED)),
        ("mandatory Excel", (RequirementImportance.PREFERRED, RequirementImportance.REQUIRED)),
    }


def test_hint_and_labeled_source_conflicts_remain_visible_without_overwrite() -> None:
    result = analyze(
        "Job Title: Source Title\nCompany: Source Company\nRequirements\n- SAP",
        title_hint="Trusted Hint",
        company_hint="Trusted Company",
    )

    assert result.profile.title == "Trusted Hint"
    assert result.profile.company == "Trusted Company"
    assert {(item.field, item.source_reference) for item in result.metadata_conflicts} == {
        ("title", "job:line:1"),
        ("company", "job:line:2"),
    }


def test_ambiguous_and_unicode_input_remains_unresolved_without_title_or_company_guessing() -> None:
    result = analyze("İlan Açıklaması\n- Üretim ortamında çalışma\n", title_hint=None, company_hint=None)

    assert result.profile.title is None and result.profile.company is None
    assert result.unresolved_items[0].original_text == "İlan Açıklaması"
    assert result.unresolved_items[1].original_text == "- Üretim ortamında çalışma"


def test_job_analysis_has_no_ai_or_career_profile_dependency() -> None:
    source = inspect.getsource(job_service)
    assert "app.ai" not in source
    assert "CareerProfile" not in source

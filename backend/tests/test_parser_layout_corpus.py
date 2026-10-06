"""Small anonymous corpus for supported and deliberately unresolved PDF layouts."""

from dataclasses import dataclass

import pymupdf
import pytest

from app.domain.document import (
    BlockType, CVDocument, CVSection, DocumentBlock, DocumentFormat, DocumentPage,
    DocumentSource, SectionType, SourceLocation,
)
from app.extraction.career import extract_career_profile
from app.parsers.pdf import parse_pdf


@dataclass(frozen=True)
class LayoutExpectation:
    name: str
    rows: tuple[tuple[str, BlockType], ...]
    sections: tuple[SectionType, ...]
    work_count: int
    projects: tuple[str, ...] = ()
    unresolved_experience: bool = False


def _document(case: LayoutExpectation) -> CVDocument:
    blocks = tuple(
        DocumentBlock(raw_text=text, block_type=kind, location=SourceLocation(page_number=1, block_index=index))
        for index, (text, kind) in enumerate(case.rows)
    )
    groups: list[CVSection] = []
    active: list[DocumentBlock] = []
    active_type: SectionType | None = None
    heading_map = {
        "WORK EXPERIENCE": SectionType.EXPERIENCE, "SKILLS": SectionType.SKILLS,
        "PROJECTS": SectionType.PROJECTS, "EDUCATION": SectionType.EDUCATION,
    }
    for block in blocks:
        section = heading_map.get(block.raw_text)
        if section is not None:
            if active_type is not None:
                groups.append(CVSection(section_type=active_type, original_heading=active[0].raw_text, block_references=tuple(item.stable_reference for item in active)))
            active_type, active = section, [block]
        elif active_type is not None:
            active.append(block)
    if active_type is not None:
        groups.append(CVSection(section_type=active_type, original_heading=active[0].raw_text, block_references=tuple(item.stable_reference for item in active)))
    return CVDocument(
        source=DocumentSource(filename=f"{case.name}.pdf", document_format=DocumentFormat.PDF, page_count=1),
        blocks=blocks,
        pages=(DocumentPage(page_number=1, block_references=tuple(block.stable_reference for block in blocks)),),
        sections=tuple(groups),
    )


CASES = (
    LayoutExpectation("classic_date_first", (
        ("WORK EXPERIENCE", BlockType.HEADING), ("Jan 2022 - Mar 2024", BlockType.PARAGRAPH),
        ("Planner, Example Logistics", BlockType.PARAGRAPH), ("- Managed demand planning", BlockType.BULLET),
        ("SKILLS", BlockType.HEADING), ("SAP", BlockType.PARAGRAPH),
    ), (SectionType.EXPERIENCE, SectionType.SKILLS), 1),
    LayoutExpectation("title_first", (
        ("WORK EXPERIENCE", BlockType.HEADING), ("Planner", BlockType.PARAGRAPH),
        ("Example Logistics", BlockType.PARAGRAPH), ("Jan 2022 - Mar 2024", BlockType.PARAGRAPH),
        ("- Managed demand planning", BlockType.BULLET),
    ), (SectionType.EXPERIENCE,), 1),
    LayoutExpectation("company_first_labelled", (
        ("WORK EXPERIENCE", BlockType.HEADING), ("Company: Example Logistics", BlockType.PARAGRAPH),
        ("Title: Planner", BlockType.PARAGRAPH), ("08/2024 - Present", BlockType.PARAGRAPH),
        ("- Own planning cadence", BlockType.BULLET),
    ), (SectionType.EXPERIENCE,), 1),
    LayoutExpectation("same_company_multi_role", (
        ("WORK EXPERIENCE", BlockType.HEADING), ("Planner", BlockType.PARAGRAPH), ("Example Logistics", BlockType.PARAGRAPH),
        ("2022 - 2023", BlockType.PARAGRAPH), ("- Role A bullet", BlockType.BULLET),
        ("Senior Planner", BlockType.PARAGRAPH), ("Example Logistics", BlockType.PARAGRAPH),
        ("2023 - Present", BlockType.PARAGRAPH), ("- Role B bullet", BlockType.BULLET),
    ), (SectionType.EXPERIENCE,), 2),
    LayoutExpectation("project_words_are_not_projects", (
        ("WORK EXPERIENCE", BlockType.HEADING), ("Planner", BlockType.PARAGRAPH), ("Example Logistics", BlockType.PARAGRAPH),
        ("2022 - Present", BlockType.PARAGRAPH), ("- Worked on multiple projects", BlockType.BULLET),
        ("- Project follow-up", BlockType.BULLET), ("- Project coordination", BlockType.BULLET),
    ), (SectionType.EXPERIENCE,), 1),
)


@pytest.mark.parametrize("case", CASES, ids=lambda item: item.name)
def test_supported_layout_corpus_has_explicit_expected_profile(case: LayoutExpectation) -> None:
    result = extract_career_profile(_document(case))

    assert tuple(section.section_type for section in _document(case).sections) == case.sections
    assert len(result.profile.work_experiences) == case.work_count
    assert tuple(project.name for project in result.profile.projects) == case.projects
    assert all(fact.source.reference.startswith("page:1:block:") for role in result.profile.work_experiences for fact in role.facts)
    experience_unresolved = any(item.section_type is SectionType.EXPERIENCE for item in result.unresolved_evidence)
    assert experience_unresolved is case.unresolved_experience


def test_same_company_roles_keep_dates_current_state_and_bullets_separate() -> None:
    profile = extract_career_profile(_document(CASES[3])).profile

    assert [(role.company, role.title) for role in profile.work_experiences] == [
        ("Example Logistics", "Planner"), ("Example Logistics", "Senior Planner"),
    ]
    assert [role.is_current for role in profile.work_experiences] == [False, True]
    assert [fact.statement for fact in profile.work_experiences[0].facts] == ["Role A bullet"]
    assert [fact.statement for fact in profile.work_experiences[1].facts] == ["Role B bullet"]


def test_ambiguous_company_first_and_interleaved_columns_stay_unresolved() -> None:
    ambiguous = LayoutExpectation("ambiguous", (
        ("WORK EXPERIENCE", BlockType.HEADING), ("Company A", BlockType.PARAGRAPH),
        ("Company B", BlockType.PARAGRAPH), ("Title A", BlockType.PARAGRAPH),
        ("Title B", BlockType.PARAGRAPH), ("2022 - 2024", BlockType.PARAGRAPH),
        ("2023 - Present", BlockType.PARAGRAPH), ("SKILLS", BlockType.HEADING),
        ("SAP", BlockType.PARAGRAPH), ("Python", BlockType.PARAGRAPH),
    ), (SectionType.EXPERIENCE, SectionType.SKILLS), 0, unresolved_experience=True)
    result = extract_career_profile(_document(ambiguous))

    assert result.profile.work_experiences == ()
    assert [fact.statement for fact in result.profile.skills] == ["SAP", "Python"]
    assert any(item.section_type is SectionType.EXPERIENCE for item in result.unresolved_evidence)


def test_same_company_without_a_repeated_company_is_not_assumed_or_leaked() -> None:
    no_repeat = LayoutExpectation("same-company-no-repeat", (
        ("WORK EXPERIENCE", BlockType.HEADING), ("Planner", BlockType.PARAGRAPH),
        ("Example Logistics", BlockType.PARAGRAPH), ("2022 - 2023", BlockType.PARAGRAPH),
        ("- Role A bullet", BlockType.BULLET), ("Senior Planner", BlockType.PARAGRAPH),
        ("2023 - Present", BlockType.PARAGRAPH), ("- Role B bullet", BlockType.BULLET),
    ), (SectionType.EXPERIENCE,), 1, unresolved_experience=True)
    result = extract_career_profile(_document(no_repeat))

    assert [(role.company, role.title) for role in result.profile.work_experiences] == [("Example Logistics", "Planner")]
    assert [fact.statement for fact in result.profile.work_experiences[0].facts] == ["Role A bullet"]
    assert len(result.work_experience_candidates) == 1
    partial = result.work_experience_candidates[0]
    assert partial.company is None and partial.title.value == "Senior Planner"
    assert partial.start_date.value.year == 2023 and partial.is_current.value is True
    assert {source.original_text.strip() for source in partial.origin.evidence_sources} >= {"Senior Planner", "- Role B bullet"}
    assert any(item.section_type is SectionType.EXPERIENCE for item in result.unresolved_evidence)


@pytest.mark.parametrize("heading, expected", [
    ("Experience", SectionType.EXPERIENCE), ("Work Experience", SectionType.EXPERIENCE),
    ("Professional Experience", SectionType.EXPERIENCE), ("Employment History", SectionType.EXPERIENCE),
    ("Skills", SectionType.SKILLS), ("Technical Skills", SectionType.SKILLS),
    ("Professional Skills", SectionType.SKILLS), ("Core Competencies", SectionType.SKILLS),
    ("Education", SectionType.EDUCATION), ("Academic Background", SectionType.EDUCATION),
    ("Academic Experience", SectionType.EDUCATION), ("Projects", SectionType.PROJECTS),
    ("Selected Projects", SectionType.PROJECTS), ("Academic Projects", SectionType.PROJECTS),
])
def test_pdf_section_alias_corpus(heading: str, expected: SectionType) -> None:
    pdf = pymupdf.open(); page = pdf.new_page(); page.insert_text((72, 72), heading, fontsize=11)
    page.insert_text((72, 96), "Example content", fontsize=11); data = pdf.tobytes(); pdf.close()

    document = parse_pdf(data, "aliases.pdf")
    assert document.sections[0].section_type is expected


def test_project_section_keeps_explicit_named_projects_without_generic_work_bullets() -> None:
    case = LayoutExpectation("projects", (
        ("PROJECTS", BlockType.HEADING), ("Warehouse Optimization", BlockType.BULLET),
        ("Supply Planning Improvement", BlockType.BULLET),
    ), (SectionType.PROJECTS,), 0, projects=("Warehouse Optimization", "Supply Planning Improvement"))
    result = extract_career_profile(_document(case))
    assert tuple(item.name for item in result.profile.projects) == case.projects

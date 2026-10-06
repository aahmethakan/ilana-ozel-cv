"""Geometry-backed PDF fixtures: evidence layout improves order, never verification."""

import pymupdf

from app.domain.document import BlockType, SectionType
from app.extraction.career import extract_career_profile
from app.parsers.pdf import parse_pdf


def _pdf(pages: tuple[tuple[tuple[float, float, str], ...], ...]) -> bytes:
    document = pymupdf.open()
    for rows in pages:
        page = document.new_page()
        for x, y, text in rows:
            page.insert_text((x, y), text, fontsize=10)
    data = document.tobytes(); document.close()
    return data


def test_two_column_geometry_preserves_left_experience_and_right_skills() -> None:
    document = parse_pdf(_pdf(((
        (72, 72, "WORK EXPERIENCE"), (72, 96, "Jan 2022 - Present"),
        (72, 120, "Planner, Example Logistics"), (72, 144, "- Managed demand planning"),
        (330, 72, "SKILLS"), (330, 96, "SAP"), (330, 120, "Power BI"),
    ),)), "two-column.pdf")
    profile = extract_career_profile(document).profile

    assert [block.location.column_index for block in document.blocks] == [0, 0, 0, 0, 1, 1, 1]
    assert [block.location.reading_order for block in document.blocks] == list(range(7))
    assert all(block.location.width and block.location.height for block in document.blocks)
    assert [section.section_type for section in document.sections] == [SectionType.EXPERIENCE, SectionType.SKILLS]
    assert [role.title for role in profile.work_experiences] == ["Planner"]
    assert [fact.statement for fact in profile.skills] == ["SAP", "Power BI"]
    assert [fact.statement for fact in profile.work_experiences[0].facts] == ["Managed demand planning"]


def test_page_break_inside_role_continues_section_and_keeps_multiline_bullet_together() -> None:
    document = parse_pdf(_pdf((
        ((72, 72, "WORK EXPERIENCE"), (72, 96, "Planner, Example Logistics"), (72, 120, "Jan 2022 - Present")),
        ((72, 72, "- Supply planning based on forecast,"), (88, 88, "availability, sales, volume and waste")),
    )), "continued-role.pdf")
    profile = extract_career_profile(document).profile

    assert len(document.sections) == 1 and document.sections[0].section_type is SectionType.EXPERIENCE
    assert len(profile.work_experiences) == 1
    assert profile.work_experiences[0].facts[0].statement == "Supply planning based on forecast,\navailability, sales, volume and waste"


def test_geometry_does_not_inherit_an_omitted_company_as_verified_data() -> None:
    document = parse_pdf(_pdf(((
        (72, 72, "WORK EXPERIENCE"), (72, 96, "Planner"), (72, 120, "Example Logistics"),
        (72, 144, "2022 - 2023"), (72, 168, "- Role A bullet"),
        (72, 192, "Senior Planner"), (72, 216, "2023 - Present"), (72, 240, "- Role B bullet"),
    ),)), "company-continuation.pdf")
    result = extract_career_profile(document)

    assert [(role.company, role.title) for role in result.profile.work_experiences] == [("Example Logistics", "Planner")]
    assert [fact.statement for fact in result.profile.work_experiences[0].facts] == ["Role A bullet"]
    assert any(item.section_type is SectionType.EXPERIENCE for item in result.unresolved_evidence)


def test_repeated_later_page_contact_furniture_is_not_an_experience_fact() -> None:
    document = parse_pdf(_pdf((
        ((72, 72, "candidate@example.com"), (72, 120, "WORK EXPERIENCE"), (72, 144, "Jan 2022 - Present"), (72, 168, "Planner, Example Logistics")),
        ((72, 72, "candidate@example.com"), (72, 120, "- Managed demand planning")),
    )), "repeated-contact.pdf")
    profile = extract_career_profile(document).profile

    assert any(block.block_type is BlockType.UNKNOWN and block.location.page_number == 2 for block in document.blocks)
    assert [fact.statement for fact in profile.work_experiences[0].facts] == ["Managed demand planning"]

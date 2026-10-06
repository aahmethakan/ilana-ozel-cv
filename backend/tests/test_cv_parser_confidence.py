from collections.abc import Sequence
import asyncio

import httpx
import pymupdf

from app.domain.career import VerificationStatus
from app.domain.document import ParserConfidence, SectionType
from app.extraction.career import extract_career_profile, parse_date_range
from app.parsers.pdf import parse_pdf
from app.main import app


def make_pdf(lines: Sequence[tuple[float, str]]) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for y_position, text in lines:
        page.insert_text((72, y_position), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return data


def parse(lines: Sequence[tuple[float, str]]):
    return parse_pdf(make_pdf(lines), "identity.pdf")


def test_clean_header_promotes_only_high_confidence_identity_and_contact() -> None:
    document = parse([
        (72, "John Smith"), (96, "Mechanical Engineer"), (120, "john@example.com"),
        (144, "+90 555 123 45 67"), (168, "linkedin.com/in/johnsmith"),
        (210, "TECHNICAL SKILLS"), (234, "CATIA, SAP"),
    ])

    result = extract_career_profile(document)

    assert result.profile.full_name == "John Smith"
    assert result.profile.headline == "Mechanical Engineer"
    assert result.profile.identity is not None
    assert result.profile.identity.name.verification_status is VerificationStatus.VERIFIED
    assert result.profile.contact.email.value == "john@example.com"
    assert result.profile.contact.email.verification_status is VerificationStatus.VERIFIED
    assert document.sections[0].section_type is SectionType.SKILLS
    assert document.sections[0].confidence is ParserConfidence.HIGH
    assert document.sections[0].block_references[-1] == "page:1:block:6"


def test_ambiguous_names_are_document_evidence_not_profile_identity() -> None:
    document = parse([(72, "John Smith"), (96, "Jane Smith"), (120, "john@example.com"), (180, "SKILLS")])

    result = extract_career_profile(document)

    assert result.profile.full_name is None
    assert result.profile.identity is None
    assert {item.confidence for item in document.identity_evidence if item.field.value == "name"} == {ParserConfidence.UNRESOLVED}
    assert {item.reason for item in result.unresolved_evidence} >= {"name_unresolved"}


def test_multiple_header_emails_are_not_randomly_promoted() -> None:
    result = extract_career_profile(parse([
        (72, "John Smith"), (96, "john@example.com"), (120, "john.smith@company.com"), (180, "SKILLS"),
    ]))

    assert result.profile.contact is None
    assert {item.reason for item in result.unresolved_evidence} >= {"ambiguous_email"}


def test_historical_work_title_never_becomes_candidate_headline_or_current_role() -> None:
    result = extract_career_profile(parse([
        (72, "John Smith"), (160, "WORK HISTORY"), (184, "2023 -"),
        (208, "Installation Engineer"), (232, "Example Systems"),
    ]))

    assert result.profile.headline is None
    assert result.profile.work_experiences[0].title == "Installation Engineer"
    assert result.profile.work_experiences[0].is_current is False
    assert result.profile.work_experiences[0].date_range_open is True


def test_footer_contact_is_not_promoted_without_header_or_contact_section() -> None:
    result = extract_career_profile(parse([
        (72, "John Smith"), (120, "WORK EXPERIENCE"), (144, "2022 - 2024"),
        (168, "Engineer"), (192, "Example Systems"), (700, "john@example.com"),
    ]))

    assert result.profile.contact is None


def test_section_aliases_and_unknown_heading_are_deterministic() -> None:
    document = parse([
        (72, "PROFESSIONAL EXPERIENCE"), (96, "ACADEMIC BACKGROUND"),
        (120, "TECHNICAL SKILLS"), (144, "UNRECOGNIZED HEADING"),
    ])

    assert [section.section_type for section in document.sections] == [
        SectionType.EXPERIENCE, SectionType.EDUCATION, SectionType.SKILLS,
    ]
    assert all(section.confidence is ParserConfidence.HIGH for section in document.sections)


def test_partial_dates_preserve_precision_and_missing_end_is_not_current() -> None:
    year = parse_date_range("2022 - 2024")
    month = parse_date_range("March 2023 -")

    assert year is not None and year.start.month is None and year.end is not None and year.end.month is None
    assert month is not None and month.start.month == 3 and month.is_open_ended and not month.is_current


def test_analysis_api_returns_authoritative_identity_without_internal_block_ids() -> None:
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/cv/analyze", files={
                "file": ("clean.pdf", make_pdf([(72, "John Smith"), (96, "Mechanical Engineer"), (120, "john@example.com"), (180, "SKILLS"), (204, "CATIA")]), "application/pdf"),
            })

    response = asyncio.run(request())

    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["full_name"] == "John Smith"
    assert profile["headline"] == "Mechanical Engineer"
    assert profile["contact"]["email"]["value"] == "john@example.com"
    assert "identity" not in profile
    assert "page:1:block:" not in str(profile)

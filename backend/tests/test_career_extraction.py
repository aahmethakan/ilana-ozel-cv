from app.domain.document import (
    BlockType,
    CVDocument,
    CVSection,
    DocumentBlock,
    DocumentFormat,
    DocumentPage,
    DocumentSource,
    SectionType,
    SourceLocation,
)
from app.extraction.career import extract_career_profile, parse_date_range
from app.services.career_gap_analysis import analyze_career_profile_gaps
from app.services.cv_quality_analysis import analyze_cv_quality


def document_with_sections(
    section_specs: list[tuple[SectionType, list[tuple[str, BlockType]]]],
    extra_blocks: list[tuple[str, BlockType]] | None = None,
) -> CVDocument:
    blocks: list[DocumentBlock] = []
    sections: list[CVSection] = []

    def add(text: str, block_type: BlockType) -> DocumentBlock:
        block = DocumentBlock(
            raw_text=text,
            block_type=block_type,
            location=SourceLocation(page_number=1, block_index=len(blocks)),
        )
        blocks.append(block)
        return block

    for text, block_type in extra_blocks or []:
        add(text, block_type)
    for section_type, entries in section_specs:
        heading = add(section_type.value.upper(), BlockType.HEADING)
        section_blocks = [heading]
        section_blocks.extend(add(text, block_type) for text, block_type in entries)
        sections.append(
            CVSection(
                section_type=section_type,
                original_heading=heading.raw_text,
                block_references=tuple(block.stable_reference for block in section_blocks),
            )
        )

    return CVDocument(
        source=DocumentSource(filename="synthetic.pdf", document_format=DocumentFormat.PDF, page_count=1),
        blocks=tuple(blocks),
        pages=(DocumentPage(page_number=1, block_references=tuple(block.stable_reference for block in blocks)),),
        sections=tuple(sections),
    )


def test_extracts_explicit_contact_values_with_provenance() -> None:
    document = document_with_sections(
        [],
        extra_blocks=[("name@example.com | +90 555 123 45 67 | linkedin.com/in/example", BlockType.CONTACT)],
    )

    result = extract_career_profile(document)

    assert result.profile.contact is not None
    assert result.profile.contact.email.value == "name@example.com"
    assert result.profile.contact.phone.value == "+90 555 123 45 67"
    assert result.profile.contact.website.value == "linkedin.com/in/example"
    assert result.profile.contact.email.source.reference == "page:1:block:0"


def test_contact_source_preserves_turkish_unicode() -> None:
    source_text = "İletişim: aday@example.com"
    document = document_with_sections([], extra_blocks=[(source_text, BlockType.CONTACT)])

    result = extract_career_profile(document)

    assert result.profile.contact is not None
    assert result.profile.contact.email.source.original_text == source_text


def test_extracts_skill_bullet_entries_without_inflation() -> None:
    document = document_with_sections(
        [(SectionType.SKILLS, [("- CATIA", BlockType.BULLET), ("- SAP", BlockType.BULLET)])]
    )

    result = extract_career_profile(document)

    assert [fact.statement for fact in result.profile.skills] == ["CATIA", "SAP"]
    assert "SAP ERP" not in [fact.statement for fact in result.profile.skills]
    assert result.profile.skills[1].source.reference == "page:1:block:2"


def test_extracts_comma_separated_explicit_skill_list() -> None:
    document = document_with_sections(
        [(SectionType.SKILLS, [("Python, FastAPI; PostgreSQL", BlockType.PARAGRAPH)])]
    )

    result = extract_career_profile(document)

    assert [fact.statement for fact in result.profile.skills] == ["Python", "FastAPI", "PostgreSQL"]


def test_ignores_layout_only_bullet_blocks_before_explicit_skill_text() -> None:
    document = document_with_sections(
        [(SectionType.SKILLS, [("\uf0b7", BlockType.BULLET), ("Tool Name", BlockType.PARAGRAPH)])]
    )

    result = extract_career_profile(document)

    assert [fact.statement for fact in result.profile.skills] == ["Tool Name"]
    assert result.unresolved_evidence == ()


def test_does_not_split_narrative_skill_sentence() -> None:
    document = document_with_sections(
        [(SectionType.SKILLS, [("Experience with SAP, automation design.", BlockType.PARAGRAPH)])]
    )

    result = extract_career_profile(document)

    assert result.profile.skills == ()
    assert result.unresolved_evidence[0].reason == "ambiguous_skill_content"


def test_extracts_language_with_explicit_proficiency() -> None:
    document = document_with_sections([(SectionType.LANGUAGES, [("English - B2", BlockType.BULLET)])])

    result = extract_career_profile(document)

    assert result.profile.languages[0].language == "English"
    assert result.profile.languages[0].proficiency == "B2"


def test_extracts_known_language_without_proficiency() -> None:
    document = document_with_sections([(SectionType.LANGUAGES, [("Türkçe", BlockType.BULLET)])])

    result = extract_career_profile(document)

    assert result.profile.languages[0].language == "Türkçe"
    assert result.profile.languages[0].proficiency is None


def test_extracts_flattened_inline_section_records_without_user_specific_rules() -> None:
    document = document_with_sections(
        [
            (SectionType.EDUCATION, [("University\n: Example Technical University\nDepartment\n: Systems Engineering (2016-2020)\nHigh School\n: Example Science High School (2012-2016)", BlockType.PARAGRAPH)]),
            (SectionType.EXPERIENCE, [("Product Specialist — Example Systems (Jan 2020 - Present)\n- Delivered explicit customer workflows", BlockType.PARAGRAPH)]),
            (SectionType.PROJECTS, [("Customer Onboarding Upgrade - (Example Systems/Jan 2023-Present)", BlockType.PARAGRAPH)]),
            (SectionType.LANGUAGES, [("Turkish (Native), English (Upper intermediate)", BlockType.PARAGRAPH)]),
            (SectionType.SKILLS, [("SQL, Python, API Design\nACTIVITIES\nBasketball", BlockType.PARAGRAPH)]),
        ]
    )

    result = extract_career_profile(document)
    profile = result.profile
    quality = analyze_cv_quality(profile, document=document, unresolved_evidence=result.unresolved_evidence)
    coach = analyze_career_profile_gaps(profile)

    assert [(item.institution, item.start_date.year if item.start_date else None) for item in profile.education] == [
        ("Example Technical University", 2016), ("Example Science High School", 2012)
    ]
    assert [(item.title, item.company) for item in profile.work_experiences] == [("Product Specialist", "Example Systems")]
    assert [item.name for item in profile.projects] == ["Customer Onboarding Upgrade"]
    assert [(item.language, item.proficiency) for item in profile.languages] == [
        ("Turkish", "Native"), ("English", "Upper intermediate")
    ]
    assert [item.statement for item in profile.skills] == ["SQL", "Python", "API Design"]
    assert "education_missing" not in {item.code for item in quality.findings}
    assert "languages_missing" not in {item.code for item in quality.findings}
    assert all(question.category.value != "language" for question in coach.questions)


def test_extracts_simple_certification_project_and_publication() -> None:
    document = document_with_sections(
        [
            (SectionType.CERTIFICATIONS, [("- Safety Training", BlockType.BULLET)]),
            (SectionType.PROJECTS, [("Production Line Upgrade", BlockType.BULLET)]),
            (SectionType.PUBLICATIONS, [("Automation Journal Article", BlockType.BULLET)]),
        ]
    )

    result = extract_career_profile(document)

    assert result.profile.certifications[0].name == "Safety Training"
    assert result.profile.projects[0].name == "Production Line Upgrade"
    assert result.profile.projects[0].facts[0].source.reference == "page:1:block:3"
    assert result.profile.publications[0].title == "Automation Journal Article"


def test_parses_common_date_ranges_without_inventing_days() -> None:
    year_range = parse_date_range("2020 - 2023")
    month_range = parse_date_range("Jan 2020 - Mar 2023")
    current_range = parse_date_range("03/2020 - Present")

    assert year_range is not None and year_range.start.month is None and year_range.end is not None
    assert month_range is not None and month_range.start.month == 1 and month_range.end.month == 3
    assert current_range is not None and current_range.is_current is True and current_range.end is None


def test_parses_turkish_month_and_rejects_ambiguous_numeric_date() -> None:
    parsed = parse_date_range("Mart 2020 – Ağustos 2023")

    assert parsed is not None
    assert parsed.start.month == 3
    assert parsed.end is not None and parsed.end.month == 8
    assert parse_date_range("03-04-2020") is None


def test_parses_open_date_range_without_claiming_current_role() -> None:
    parsed = parse_date_range("May 2024 -")

    assert parsed is not None
    assert parsed.is_open_ended is True
    assert parsed.is_current is False


def test_ambiguous_experience_and_education_remain_unresolved() -> None:
    document = document_with_sections(
        [
            (SectionType.EXPERIENCE, [("Engineer\nExample Company\n2020 - 2023", BlockType.PARAGRAPH)]),
            (SectionType.EDUCATION, [("Example University\nEngineering", BlockType.PARAGRAPH)]),
        ]
    )

    result = extract_career_profile(document)

    assert result.profile.work_experiences == ()
    assert result.profile.education == ()
    assert [item.reason for item in result.unresolved_evidence] == [
        "ambiguous_experience_content",
        "ambiguous_education_content",
    ]


def test_result_is_json_serializable_and_unresolved_references_are_stable() -> None:
    document = document_with_sections(
        [(SectionType.SKILLS, [("A descriptive sentence without separators.", BlockType.PARAGRAPH)])]
    )

    result = extract_career_profile(document)
    serialized = result.model_dump(mode="json")

    assert serialized["unresolved_evidence"] == [
        {
            "block_reference": "page:1:block:1",
            "section_type": "skills",
            "reason": "ambiguous_skill_content",
        }
    ]


def multi_page_reference_shape_document() -> CVDocument:
    """Generic two-page chronology: a heading may end before continuation records."""
    rows = [
        (1, "WORK EXPERIENCE", BlockType.HEADING),
        (1, "May 2024 -", BlockType.PARAGRAPH),
        (1, "Installation Engineer, Example Systems", BlockType.PARAGRAPH),
        (1, "- Planned installation and commissioning using SAP", BlockType.BULLET),
        (1, "Oct 2022 - Apr 2024", BlockType.PARAGRAPH),
        (1, "Production Engineer", BlockType.PARAGRAPH),
        (1, "Example Materials", BlockType.PARAGRAPH),
        (1, "- Increased line efficiency by 80% using OEE", BlockType.BULLET),
        (1, "Project: Vertical machining efficiency", BlockType.PARAGRAPH),
        (1, "EDUCATION", BlockType.HEADING),
        (1, "Sep 2017 - Oct 2022", BlockType.PARAGRAPH),
        (1, "Mechanical Engineering", BlockType.PARAGRAPH),
        (1, "Example Technical University", BlockType.PARAGRAPH),
        # The parser may keep these continuation records under the preceding heading.
        (2, "Feb 2022 - Oct 2022", BlockType.PARAGRAPH),
        (2, "Production Engineer Intern", BlockType.PARAGRAPH),
        (2, "Example Materials", BlockType.PARAGRAPH),
        (2, "- Supported Smartflow project", BlockType.BULLET),
        (2, "Nov 2020 - Feb 2022", BlockType.PARAGRAPH),
        (2, "Mechanical Engineer Intern", BlockType.PARAGRAPH),
        (2, "Example Engineering", BlockType.PARAGRAPH),
        (2, "- Performed ventilation calculations with REVIT", BlockType.BULLET),
        (2, "Sep 2020 - Oct 2020", BlockType.PARAGRAPH),
        (2, "Engineering Intern", BlockType.PARAGRAPH),
        (2, "Example Machinery", BlockType.PARAGRAPH),
        (2, "- Completed manufacturing and quality-control training", BlockType.BULLET),
        (2, "SKILLS", BlockType.HEADING),
        (2, "Tool A", BlockType.PARAGRAPH), (2, "Tool B", BlockType.PARAGRAPH),
        (2, "Tool C", BlockType.PARAGRAPH), (2, "Tool D", BlockType.PARAGRAPH),
        (2, "Tool E", BlockType.PARAGRAPH), (2, "Tool F", BlockType.PARAGRAPH),
        (2, "Tool G", BlockType.PARAGRAPH), (2, "Tool H", BlockType.PARAGRAPH),
        (2, "Tool I", BlockType.PARAGRAPH),
        (2, "ACCOMPLISHMENTS", BlockType.HEADING),
        (2, "Article: Assessment of a manufacturing surface", BlockType.PARAGRAPH),
        (2, "Sport activities", BlockType.PARAGRAPH),
    ]
    blocks = tuple(DocumentBlock(raw_text=text, block_type=kind, location=SourceLocation(page_number=page, block_index=index)) for index, (page, text, kind) in enumerate(rows))
    page_refs = {page: tuple(block.stable_reference for block in blocks if block.location.page_number == page) for page in (1, 2)}
    work_refs = tuple(block.stable_reference for block in blocks[:9])
    education_refs = tuple(block.stable_reference for block in blocks[9:])
    skills_start = next(index for index, block in enumerate(blocks) if block.raw_text == "SKILLS")
    additional_start = next(index for index, block in enumerate(blocks) if block.raw_text == "ACCOMPLISHMENTS")
    return CVDocument(
        source=DocumentSource(filename="two-page-reference.pdf", document_format=DocumentFormat.PDF, page_count=2),
        blocks=blocks,
        pages=(DocumentPage(page_number=1, block_references=page_refs[1]), DocumentPage(page_number=2, block_references=page_refs[2])),
        sections=(
            CVSection(section_type=SectionType.EXPERIENCE, original_heading="WORK EXPERIENCE", block_references=work_refs),
            CVSection(section_type=SectionType.EDUCATION, original_heading="EDUCATION", block_references=education_refs[:skills_start - 9]),
            CVSection(section_type=SectionType.SKILLS, original_heading="SKILLS", block_references=tuple(block.stable_reference for block in blocks[skills_start:additional_start])),
            CVSection(section_type=SectionType.ADDITIONAL, original_heading="ACCOMPLISHMENTS", block_references=tuple(block.stable_reference for block in blocks[additional_start:])),
        ),
    )


def test_generic_two_page_continuation_extracts_records_and_downstream_evidence() -> None:
    document = multi_page_reference_shape_document()
    extraction = extract_career_profile(document)
    profile = extraction.profile

    assert len(profile.work_experiences) == 5
    assert len(profile.education) == 1
    assert profile.work_experiences[0].date_range_open is True
    assert profile.work_experiences[0].is_current is False
    assert len(profile.skills) == 9
    assert any(fact.metrics and fact.metrics[0].value == 80 for item in profile.work_experiences for fact in item.facts)
    assert [item.name for item in profile.projects] == ["Vertical machining efficiency"]
    assert [item.title for item in profile.publications] == ["Assessment of a manufacturing surface"]
    assert "Sport activities" not in [item.title for item in profile.publications]

    quality = analyze_cv_quality(profile, document=document, unresolved_evidence=extraction.unresolved_evidence)
    assert "structured_experience_present" in {item.code for item in quality.findings}
    assert "structured_education_present" in {item.code for item in quality.findings}
    assert "trusted_skills_present" in {item.code for item in quality.findings}
    assert "explicit_metrics" in {item.code for item in quality.findings}
    coach = analyze_career_profile_gaps(profile)
    assert not any(question.category.value == "metric" and question.related_role == "Production Engineer" for question in coach.questions)

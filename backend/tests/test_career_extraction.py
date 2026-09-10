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

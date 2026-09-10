import json

import pytest
from pydantic import ValidationError

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


def pdf_source() -> DocumentSource:
    return DocumentSource(
        filename="ilana-cv.pdf",
        document_format=DocumentFormat.PDF,
        media_type="application/pdf",
        page_count=2,
    )


def block(page_number: int | None, block_index: int, text: str) -> DocumentBlock:
    return DocumentBlock(
        raw_text=text,
        block_type=BlockType.PARAGRAPH,
        location=SourceLocation(page_number=page_number, block_index=block_index),
    )


def valid_pdf_document() -> CVDocument:
    first_block = block(1, 0, "Automation engineer with commissioning experience.")
    second_block = block(1, 1, "Reduced setup time by 18%.")
    third_block = block(2, 0, "Bachelor's degree in Electrical Engineering.")
    return CVDocument(
        source=pdf_source(),
        blocks=(first_block, second_block, third_block),
        pages=(
            DocumentPage(
                page_number=1,
                block_references=(first_block.stable_reference, second_block.stable_reference),
            ),
            DocumentPage(page_number=2, block_references=(third_block.stable_reference,)),
        ),
        sections=(
            CVSection(
                section_type=SectionType.EXPERIENCE,
                original_heading="PROFESSIONAL BACKGROUND",
                block_references=(first_block.stable_reference, second_block.stable_reference),
            ),
            CVSection(
                section_type=SectionType.EDUCATION,
                original_heading="EDUCATION",
                block_references=(third_block.stable_reference,),
            ),
        ),
        detected_languages=("English", "Turkish"),
    )


def test_valid_pdf_document_with_two_pages() -> None:
    document = valid_pdf_document()

    assert document.source.document_format is DocumentFormat.PDF
    assert len(document.pages) == 2


def test_valid_docx_document_has_no_page_assumptions() -> None:
    document = CVDocument(
        source=DocumentSource(
            filename="ilana-cv.docx",
            document_format=DocumentFormat.DOCX,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        blocks=(block(None, 0, "Commissioning Engineer"),),
    )

    assert document.pages == ()
    assert document.blocks[0].stable_reference == "document:block:0"


def test_block_and_page_order_are_preserved() -> None:
    document = valid_pdf_document()

    assert [item.raw_text for item in document.blocks] == [
        "Automation engineer with commissioning experience.",
        "Reduced setup time by 18%.",
        "Bachelor's degree in Electrical Engineering.",
    ]
    assert [page.page_number for page in document.pages] == [1, 2]


def test_stable_source_reference_is_deterministic() -> None:
    location = SourceLocation(page_number=2, block_index=4)

    assert location.stable_reference == "page:2:block:4"
    assert location.stable_reference == "page:2:block:4"


def test_identical_text_in_distinct_blocks_has_distinct_references() -> None:
    first_block = block(None, 0, "Siemens TIA Portal")
    second_block = block(None, 1, "Siemens TIA Portal")

    assert first_block.stable_reference != second_block.stable_reference


def test_blank_filename_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DocumentSource(filename=" ", document_format=DocumentFormat.PDF)


def test_blank_required_block_text_is_rejected_without_rewriting_text() -> None:
    with pytest.raises(ValidationError):
        block(None, 0, "\t \n")


def test_invalid_page_and_block_indices_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SourceLocation(page_number=0, block_index=0)
    with pytest.raises(ValidationError):
        SourceLocation(block_index=-1)
    with pytest.raises(ValidationError):
        SourceLocation(block_index=0, start_offset=8, end_offset=7)


def test_duplicate_block_identity_is_rejected() -> None:
    duplicated_location = SourceLocation(page_number=1, block_index=0)
    first_block = DocumentBlock(
        raw_text="First text",
        block_type=BlockType.PARAGRAPH,
        location=duplicated_location,
    )
    second_block = DocumentBlock(
        raw_text="Second text",
        block_type=BlockType.PARAGRAPH,
        location=duplicated_location,
    )

    with pytest.raises(ValidationError):
        CVDocument(
            source=DocumentSource(
                filename="duplicate.docx",
                document_format=DocumentFormat.DOCX,
            ),
            blocks=(first_block, second_block),
        )


def test_section_preserves_heading_independently_from_section_type() -> None:
    section = CVSection(
        section_type=SectionType.EXPERIENCE,
        original_heading="İŞ DENEYİMİ",
    )

    assert section.original_heading == "İŞ DENEYİMİ"
    assert section.section_type is SectionType.EXPERIENCE


def test_turkish_unicode_survives_json_serialization() -> None:
    text = "Kurulum ve devreye alma süreçlerinde görev aldım: ğ ş İ ı ö ü ç"
    document = CVDocument(
        source=DocumentSource(filename="özgeçmiş.docx", document_format=DocumentFormat.DOCX),
        blocks=(block(None, 0, text),),
    )

    serialized = document.model_dump(mode="json")

    assert serialized["blocks"][0]["raw_text"] == text
    assert json.loads(json.dumps(serialized, ensure_ascii=False))["blocks"][0]["raw_text"] == text


def test_unknown_blocks_and_sections_are_preserved() -> None:
    unknown_block = DocumentBlock(
        raw_text="Unclassified source content",
        block_type=BlockType.UNKNOWN,
        location=SourceLocation(block_index=0),
    )
    document = CVDocument(
        source=DocumentSource(filename="unknown.docx", document_format=DocumentFormat.DOCX),
        blocks=(unknown_block,),
        sections=(
            CVSection(
                section_type=SectionType.UNKNOWN,
                original_heading="OTHER",
                block_references=(unknown_block.stable_reference,),
            ),
        ),
    )

    assert document.model_dump(mode="json")["sections"][0]["section_type"] == "unknown"


def test_serialization_is_deterministic() -> None:
    document = valid_pdf_document()

    assert document.model_dump(mode="json") == document.model_dump(mode="json")


def test_dangling_section_reference_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CVDocument(
            source=DocumentSource(filename="dangling.docx", document_format=DocumentFormat.DOCX),
            sections=(
                CVSection(
                    section_type=SectionType.UNKNOWN,
                    block_references=("document:block:99",),
                ),
            ),
        )

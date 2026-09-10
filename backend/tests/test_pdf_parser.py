from collections.abc import Sequence

import pymupdf
import pytest

from app.domain.document import BlockType, SectionType
from app.parsers.pdf import (
    EmptyPDFInputError,
    EncryptedPDFError,
    InvalidPDFError,
    NoMachineReadableTextError,
    PDFInputTooLargeError,
    parse_pdf,
)


def make_pdf(pages: Sequence[Sequence[tuple[float, float, str]]]) -> bytes:
    document = pymupdf.open()
    for lines in pages:
        page = document.new_page()
        for x_position, y_position, text in lines:
            page.insert_text((x_position, y_position), text, fontsize=11)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def make_unicode_pdf(text: str) -> bytes:
    encoded_text = text.encode("utf-16-be").hex().upper()
    unicode_map = "\n".join(
        f"<{ord(character):04X}> <{ord(character):04X}>" for character in sorted(set(text))
    )
    to_unicode = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\n"
        "begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n"
        "/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"{len(set(text))} beginbfchar\n{unicode_map}\nendbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode("ascii")
    content = f"BT /F1 5 Tf 72 720 Td <{encoded_text}> Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type0 /BaseFont /Helvetica /Encoding /Identity-H "
        b"/DescendantFonts [5 0 R] /ToUnicode 7 0 R >>",
        (
            b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Helvetica "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            b"/FontDescriptor 8 0 R /DW 1000 /CIDToGIDMap /Identity >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Length " + str(len(to_unicode)).encode() + b" >>\nstream\n" + to_unicode + b"endstream",
        (
            b"<< /Type /FontDescriptor /FontName /Helvetica /Flags 4 /FontBBox [0 -200 1000 900] "
            b"/ItalicAngle 0 /Ascent 800 /Descent -200 /CapHeight 700 /StemV 80 >>"
        ),
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, object_content in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode())
        output.extend(object_content)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    )
    return bytes(output)


def test_parses_valid_one_page_pdf_with_source_metadata() -> None:
    pdf_bytes = make_pdf([[(72, 72, "responsable for commisioning")]])

    document = parse_pdf(pdf_bytes, "source-cv.pdf")

    assert document.source.filename == "source-cv.pdf"
    assert document.source.page_count == 1
    assert document.pages[0].page_number == 1
    assert document.blocks[0].raw_text.strip() == "responsable for commisioning"


def test_parser_references_and_serialization_are_deterministic() -> None:
    pdf_bytes = make_pdf([[(72, 72, "EXPERIENCE"), (72, 96, "Commissioned production lines")]])

    first_document = parse_pdf(pdf_bytes, "stable.pdf")
    second_document = parse_pdf(pdf_bytes, "stable.pdf")

    assert [block.stable_reference for block in first_document.blocks] == [
        "page:1:block:0",
        "page:1:block:1",
    ]
    assert first_document.model_dump(mode="json") == second_document.model_dump(mode="json")


def test_bullets_and_english_headings_are_classified_without_rewriting() -> None:
    pdf_bytes = make_pdf([[(72, 72, "WORK EXPERIENCE"), (72, 96, "- Reduced setup time by 18%")]])

    document = parse_pdf(pdf_bytes, "bullet.pdf")

    assert document.blocks[0].block_type is BlockType.HEADING
    assert document.blocks[1].block_type is BlockType.BULLET
    assert document.blocks[1].raw_text.strip() == "- Reduced setup time by 18%"
    assert document.sections[0].section_type is SectionType.EXPERIENCE
    assert document.sections[0].original_heading.strip() == "WORK EXPERIENCE"


def test_turkish_heading_and_unicode_text_are_preserved() -> None:
    heading_document = parse_pdf(make_unicode_pdf("İŞ DENEYİMİ"), "başlık.pdf")
    text = "Kurulum ve devreye alma süreçlerinde görev aldım: ğ ş İ ı ö ü ç"

    document = parse_pdf(make_unicode_pdf(text), "özgeçmiş.pdf")

    assert heading_document.blocks[0].raw_text.strip() == "İŞ DENEYİMİ"
    assert heading_document.blocks[0].block_type is BlockType.HEADING
    assert heading_document.sections[0].section_type is SectionType.EXPERIENCE
    assert document.blocks[0].raw_text.strip() == text
    assert document.model_dump(mode="json")["blocks"][0]["raw_text"].strip() == text


def test_two_page_order_is_preserved() -> None:
    pdf_bytes = make_pdf(
        [
            [(72, 72, "First page content")],
            [(72, 72, "Second page content")],
        ]
    )

    document = parse_pdf(pdf_bytes, "two-pages.pdf")

    assert [page.page_number for page in document.pages] == [1, 2]
    assert [block.raw_text.strip() for block in document.blocks] == [
        "First page content",
        "Second page content",
    ]


def test_two_column_reading_order_is_left_column_then_right_column() -> None:
    pdf_bytes = make_pdf(
        [
            [
                (72, 72, "LEFT ONE"),
                (72, 96, "LEFT TWO"),
                (330, 72, "RIGHT ONE"),
                (330, 96, "RIGHT TWO"),
            ]
        ]
    )

    document = parse_pdf(pdf_bytes, "two-columns.pdf")

    assert [block.raw_text.strip() for block in document.blocks] == [
        "LEFT ONE",
        "LEFT TWO",
        "RIGHT ONE",
        "RIGHT TWO",
    ]


def test_two_column_order_uses_block_origins_when_text_crosses_page_midpoint() -> None:
    pdf_bytes = make_pdf(
        [
            [
                (250, 72, "DOCUMENT HEADER"),
                (50, 200, "LEFT FIRST"),
                (50, 224, "LEFT SECOND"),
                (50, 248, "LEFT THIRD"),
                (250, 200, "RIGHT FIRST EXTENDS ACROSS THE PAGE MIDPOINT"),
                (250, 224, "RIGHT SECOND EXTENDS ACROSS THE PAGE MIDPOINT"),
                (250, 248, "RIGHT THIRD EXTENDS ACROSS THE PAGE MIDPOINT"),
            ]
        ]
    )

    document = parse_pdf(pdf_bytes, "origin-columns.pdf")

    assert [block.raw_text.strip() for block in document.blocks] == [
        "DOCUMENT HEADER",
        "LEFT FIRST",
        "LEFT SECOND",
        "LEFT THIRD",
        "RIGHT FIRST EXTENDS ACROSS THE PAGE MIDPOINT",
        "RIGHT SECOND EXTENDS ACROSS THE PAGE MIDPOINT",
        "RIGHT THIRD EXTENDS ACROSS THE PAGE MIDPOINT",
    ]


def test_merged_recognized_heading_lines_become_independent_sections() -> None:
    pdf_bytes = make_pdf([[(72, 72, "WORK EXPERIENCE\nPERSONAL PROFILE")]])

    document = parse_pdf(pdf_bytes, "merged-headings.pdf")

    assert [block.raw_text.strip() for block in document.blocks] == [
        "WORK EXPERIENCE",
        "PERSONAL PROFILE",
    ]
    assert [section.section_type for section in document.sections] == [
        SectionType.EXPERIENCE,
        SectionType.SUMMARY,
    ]


def test_common_cv_heading_aliases_are_normalized_conservatively() -> None:
    pdf_bytes = make_pdf(
        [
            [
                (72, 72, "ACADEMIC BACKGROUND"),
                (72, 96, "PROFESSIONAL SKILLS"),
                (72, 120, "ACCOMPLISHMENTS"),
                (72, 144, "EDUCATION AND TRAINING"),
            ]
        ]
    )

    document = parse_pdf(pdf_bytes, "heading-aliases.pdf")

    assert [section.section_type for section in document.sections] == [
        SectionType.EDUCATION,
        SectionType.SKILLS,
        SectionType.ADDITIONAL,
        SectionType.EDUCATION,
    ]


def test_private_use_bullet_markers_are_preserved_and_classified() -> None:
    document = parse_pdf(make_unicode_pdf("\uf09f Source evidence bullet"), "symbol-bullet.pdf")

    assert document.blocks[0].block_type is BlockType.BULLET
    assert document.blocks[0].raw_text.strip() == "\uf09f Source evidence bullet"


def test_bullet_lines_are_split_without_rewriting_surrounding_text() -> None:
    pdf_bytes = make_pdf([[(72, 72, "ROLE\n- First responsibility\n- Second responsibility\nNotes")]])

    document = parse_pdf(pdf_bytes, "bullet-lines.pdf")

    assert [block.block_type for block in document.blocks] == [
        BlockType.PARAGRAPH,
        BlockType.BULLET,
        BlockType.BULLET,
        BlockType.PARAGRAPH,
    ]
    assert [block.raw_text.strip() for block in document.blocks] == [
        "ROLE",
        "- First responsibility",
        "- Second responsibility",
        "Notes",
    ]


def test_uppercase_single_token_technologies_are_not_headings() -> None:
    pdf_bytes = make_pdf([[(72, 72, "INDUSTRIAL ENGINEER"), (72, 96, "CATIA"), (72, 120, "MATLAB")]])

    document = parse_pdf(pdf_bytes, "technology-labels.pdf")

    assert [block.block_type for block in document.blocks] == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
    ]


def test_invalid_and_empty_pdf_inputs_raise_parser_errors() -> None:
    with pytest.raises(EmptyPDFInputError):
        parse_pdf(b"", "empty.pdf")
    with pytest.raises(EmptyPDFInputError):
        parse_pdf(b"%PDF", " ")
    with pytest.raises(InvalidPDFError):
        parse_pdf(b"not a PDF", "invalid.pdf")


def test_no_machine_readable_text_pdf_is_rejected() -> None:
    empty_document = pymupdf.open()
    empty_document.new_page()
    pdf_bytes = empty_document.tobytes()
    empty_document.close()

    with pytest.raises(NoMachineReadableTextError, match="machine-readable text"):
        parse_pdf(pdf_bytes, "scanned.pdf")


def test_password_protected_pdf_is_rejected() -> None:
    encrypted_document = pymupdf.open()
    page = encrypted_document.new_page()
    page.insert_text((72, 72), "Protected source text")
    pdf_bytes = encrypted_document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    encrypted_document.close()

    with pytest.raises(EncryptedPDFError, match="password-protected"):
        parse_pdf(pdf_bytes, "protected.pdf")


def test_oversized_pdf_is_rejected_before_parsing() -> None:
    with pytest.raises(PDFInputTooLargeError):
        parse_pdf(b"x" * 11, "large.pdf", max_file_size=10)

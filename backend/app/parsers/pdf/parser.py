import re
import unicodedata
from collections.abc import Iterable

import pymupdf

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
from app.parsers.pdf.exceptions import (
    EmptyPDFInputError,
    EncryptedPDFError,
    InvalidPDFError,
    NoMachineReadableTextError,
    PDFInputTooLargeError,
)

DEFAULT_MAX_PDF_BYTES = 10 * 1024 * 1024

_BULLET_LINE_PATTERN = re.compile(
    r"^\s*(?:[\u2022\u2023\u25e6\u2043\u2219\-*–—]|[\ue000-\uf8ff])(?:\s+|$)"
)
_CONTACT_PATTERN = re.compile(
    r"(?:\b[\w.+-]+@[\w-]+\.[\w.-]+\b|\b(?:linkedin\.com|www\.)|\+?\d[\d\s().-]{6,}\d)"
)
_SECTION_HEADINGS = {
    "contact": SectionType.CONTACT,
    "iletişim": SectionType.CONTACT,
    "summary": SectionType.SUMMARY,
    "profile": SectionType.SUMMARY,
    "personal profile": SectionType.SUMMARY,
    "profil": SectionType.SUMMARY,
    "özet": SectionType.SUMMARY,
    "experience": SectionType.EXPERIENCE,
    "work experience": SectionType.EXPERIENCE,
    "professional experience": SectionType.EXPERIENCE,
    "iş deneyimi": SectionType.EXPERIENCE,
    "deneyim": SectionType.EXPERIENCE,
    "education": SectionType.EDUCATION,
    "education and training": SectionType.EDUCATION,
    "academic background": SectionType.EDUCATION,
    "eğitim": SectionType.EDUCATION,
    "skills": SectionType.SKILLS,
    "professional skills": SectionType.SKILLS,
    "beceriler": SectionType.SKILLS,
    "yetkinlikler": SectionType.SKILLS,
    "languages": SectionType.LANGUAGES,
    "language skills": SectionType.LANGUAGES,
    "diller": SectionType.LANGUAGES,
    "certifications": SectionType.CERTIFICATIONS,
    "certificates": SectionType.CERTIFICATIONS,
    "sertifikalar": SectionType.CERTIFICATIONS,
    "projects": SectionType.PROJECTS,
    "projeler": SectionType.PROJECTS,
    "publications": SectionType.PUBLICATIONS,
    "achievements": SectionType.ADDITIONAL,
    "accomplishments": SectionType.ADDITIONAL,
    "volunteer work": SectionType.ADDITIONAL,
    "yayınlar": SectionType.PUBLICATIONS,
}


class PDFParser:
    """Extracts text-based PDF source evidence without career interpretation."""

    def __init__(self, max_file_size: int = DEFAULT_MAX_PDF_BYTES) -> None:
        if max_file_size <= 0:
            raise ValueError("Maximum PDF file size must be greater than zero.")
        self._max_file_size = max_file_size

    def parse(self, pdf_bytes: bytes, filename: str) -> CVDocument:
        self._validate_input(pdf_bytes, filename)
        try:
            document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception as error:
            raise InvalidPDFError("The supplied file is not a readable PDF.") from error

        try:
            if document.needs_pass:
                raise EncryptedPDFError("The PDF is password-protected and cannot be read.")

            blocks, pages = self._extract_pages(document)
        except (EncryptedPDFError, NoMachineReadableTextError):
            raise
        except Exception as error:
            raise InvalidPDFError("The supplied PDF could not be read.") from error
        finally:
            document.close()

        if not blocks:
            raise NoMachineReadableTextError(
                "No machine-readable text was found; the PDF may be scanned or image-based."
            )

        return CVDocument(
            source=DocumentSource(
                filename=filename,
                document_format=DocumentFormat.PDF,
                media_type="application/pdf",
                page_count=len(pages),
            ),
            blocks=tuple(blocks),
            pages=tuple(pages),
            sections=self._build_sections(blocks),
        )

    def _validate_input(self, pdf_bytes: bytes, filename: str) -> None:
        if not filename or not filename.strip():
            raise EmptyPDFInputError("A non-blank PDF filename is required.")
        if not pdf_bytes:
            raise EmptyPDFInputError("PDF input bytes cannot be empty.")
        if len(pdf_bytes) > self._max_file_size:
            raise PDFInputTooLargeError(
                f"PDF input exceeds the {self._max_file_size}-byte parser limit."
            )

    def _extract_pages(
        self, document: pymupdf.Document
    ) -> tuple[list[DocumentBlock], list[DocumentPage]]:
        blocks: list[DocumentBlock] = []
        pages: list[DocumentPage] = []

        for page_number, page in enumerate(document, start=1):
            page_blocks = self._ordered_text_blocks(page)
            page_references: list[str] = []
            block_index = 0
            for text_block in page_blocks:
                for raw_text in self._split_source_text(text_block[4]):
                    block = DocumentBlock(
                        raw_text=raw_text,
                        block_type=self._classify_block(raw_text, page_number, block_index),
                        location=SourceLocation(page_number=page_number, block_index=block_index),
                    )
                    blocks.append(block)
                    page_references.append(block.stable_reference)
                    block_index += 1
            pages.append(DocumentPage(page_number=page_number, block_references=tuple(page_references)))

        return blocks, pages

    def _ordered_text_blocks(self, page: pymupdf.Page) -> list[tuple[float, ...]]:
        text_blocks = [
            block
            for block in page.get_text("blocks")
            if len(block) >= 5 and isinstance(block[4], str) and block[4].strip()
        ]
        if not text_blocks:
            return []

        column_order = self._two_column_order(text_blocks, page.rect.width)
        if column_order is not None:
            return column_order
        return sorted(text_blocks, key=self._top_left_key)

    def _two_column_order(
        self, text_blocks: list[tuple[float, ...]], page_width: float
    ) -> list[tuple[float, ...]] | None:
        x_origins = sorted({round(block[0], 3) for block in text_blocks})
        if len(x_origins) < 2:
            return None

        gap_start, gap_end = max(
            zip(x_origins, x_origins[1:]), key=lambda gap: gap[1] - gap[0]
        )
        if gap_end - gap_start < page_width * 0.25:
            return None

        column_boundary = (gap_start + gap_end) / 2
        left = [block for block in text_blocks if block[0] < column_boundary]
        right = [block for block in text_blocks if block[0] >= column_boundary]
        body_start = max(min(block[1] for block in left), min(block[1] for block in right))
        left_body = [block for block in left if block[1] >= body_start]
        right_body = [block for block in right if block[1] >= body_start]
        if len(left_body) < 2 or len(right_body) < 2:
            return None

        preamble = [block for block in text_blocks if block[1] < body_start]
        return (
            sorted(preamble, key=self._top_left_key)
            + sorted(left_body, key=self._top_left_key)
            + sorted(right_body, key=self._top_left_key)
        )

    @staticmethod
    def _top_left_key(block: tuple[float, ...]) -> tuple[float, float]:
        return (round(block[1], 3), round(block[0], 3))

    def _classify_block(self, raw_text: str, page_number: int, block_index: int) -> BlockType:
        normalized_heading = self._normalized_heading(raw_text)
        if normalized_heading in _SECTION_HEADINGS or self._looks_like_uppercase_heading(raw_text):
            return BlockType.HEADING
        if _BULLET_LINE_PATTERN.match(raw_text):
            return BlockType.BULLET
        if page_number == 1 and block_index <= 5 and _CONTACT_PATTERN.search(raw_text):
            return BlockType.CONTACT
        return BlockType.PARAGRAPH

    def _split_source_text(self, raw_text: str) -> tuple[str, ...]:
        lines = tuple(raw_text.splitlines(keepends=True))
        if len(lines) > 1 and all(
            line.strip() and self._normalized_heading(line) in _SECTION_HEADINGS for line in lines
        ):
            return lines
        if not any(_BULLET_LINE_PATTERN.match(line) for line in lines):
            return (raw_text,)

        segments: list[str] = []
        non_bullet_lines: list[str] = []
        bullet_lines: list[str] = []

        def flush_non_bullet() -> None:
            if non_bullet_lines:
                segments.append("".join(non_bullet_lines))
                non_bullet_lines.clear()

        def flush_bullet() -> None:
            if bullet_lines:
                segments.append("".join(bullet_lines))
                bullet_lines.clear()

        for line in lines:
            if _BULLET_LINE_PATTERN.match(line):
                flush_non_bullet()
                flush_bullet()
                bullet_lines.append(line)
            elif bullet_lines and self._is_bullet_continuation(line):
                bullet_lines.append(line)
            else:
                flush_bullet()
                non_bullet_lines.append(line)

        flush_non_bullet()
        flush_bullet()
        return tuple(segment for segment in segments if segment.strip())

    @staticmethod
    def _is_bullet_continuation(line: str) -> bool:
        stripped_line = line.strip()
        return not stripped_line or line[:1].isspace() or stripped_line[:1].islower()

    @staticmethod
    def _normalized_heading(raw_text: str) -> str:
        normalized = unicodedata.normalize("NFKC", raw_text).strip().rstrip(":").casefold()
        return " ".join(normalized.replace("\u0307", "").split())

    def _looks_like_uppercase_heading(self, raw_text: str) -> bool:
        text = raw_text.strip()
        word_count = sum(
            any(character.isalnum() for character in token) for token in text.split()
        )
        return (
            "\n" not in text
            and len(text) <= 60
            and text.isupper()
            and word_count >= 2
            and not any(character in text for character in "-–—")
            and any(character.isalpha() for character in text)
        )

    def _build_sections(self, blocks: Iterable[DocumentBlock]) -> tuple[CVSection, ...]:
        sections: list[CVSection] = []
        active_section_type: SectionType | None = None
        active_heading: str | None = None
        active_references: list[str] = []

        def close_active_section() -> None:
            if active_section_type is not None:
                sections.append(
                    CVSection(
                        section_type=active_section_type,
                        original_heading=active_heading,
                        block_references=tuple(active_references),
                    )
                )

        for block in blocks:
            section_type = _SECTION_HEADINGS.get(self._normalized_heading(block.raw_text))
            if section_type is not None:
                close_active_section()
                active_section_type = section_type
                active_heading = block.raw_text
                active_references = [block.stable_reference]
            elif active_section_type is not None:
                active_references.append(block.stable_reference)

        close_active_section()
        return tuple(sections)


def parse_pdf(
    pdf_bytes: bytes,
    filename: str,
    *,
    max_file_size: int = DEFAULT_MAX_PDF_BYTES,
) -> CVDocument:
    """Parse PDF bytes into immutable source-document evidence."""

    return PDFParser(max_file_size=max_file_size).parse(pdf_bytes, filename)

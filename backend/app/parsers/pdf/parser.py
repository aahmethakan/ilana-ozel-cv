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
    IdentityEvidence,
    IdentityField,
    ParserConfidence,
    SectionType,
    SourceLocation,
)
from app.parsers.pdf.exceptions import (
    EmptyPDFInputError,
    EncryptedPDFError,
    InvalidPDFError,
    NoMachineReadableTextError,
    PDFInputTooLargeError,
    PDFPageLimitExceededError,
)

DEFAULT_MAX_PDF_BYTES = 10 * 1024 * 1024

_BULLET_LINE_PATTERN = re.compile(
    r"^\s*(?:[\u2022\u2023\u25e6\u2043\u2219\-*–—]|[\ue000-\uf8ff])(?:\s+|$)"
)
_CONTACT_PATTERN = re.compile(
    r"(?:\b[\w.+-]+@[\w-]+\.[\w.-]+\b|\b(?:linkedin\.com|www\.)|\+?\d[\d\s().-]{6,}\d)"
)
_EMAIL_VALUE_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE_VALUE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
_WEBSITE_VALUE_PATTERN = re.compile(r"\b(?:https?://|www\.|(?:www\.)?linkedin\.com/)[^\s,;]+", re.I)
_NAME_EXCLUSIONS = ("university", "college", "institute", "school", "company", "ltd", "inc", "profile", "summary", "experience", "education", "engineering", "science", "technology", "business", "management")
_TITLE_SUFFIXES = ("engineer", "manager", "developer", "designer", "analyst", "consultant", "specialist", "technician", "architect", "director", "lead")
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
    "work history": SectionType.EXPERIENCE,
    "professional experience": SectionType.EXPERIENCE,
    "employment history": SectionType.EXPERIENCE,
    "iş deneyimi": SectionType.EXPERIENCE,
    "deneyim": SectionType.EXPERIENCE,
    "education": SectionType.EDUCATION,
    "education and training": SectionType.EDUCATION,
    "academic background": SectionType.EDUCATION,
    "academic experience": SectionType.EDUCATION,
    "eğitim": SectionType.EDUCATION,
    "skills": SectionType.SKILLS,
    "professional skills": SectionType.SKILLS,
    "technical skills": SectionType.SKILLS,
    "computer skills": SectionType.SKILLS,
    "core competencies": SectionType.SKILLS,
    "beceriler": SectionType.SKILLS,
    "yetkinlikler": SectionType.SKILLS,
    "languages": SectionType.LANGUAGES,
    "language skills": SectionType.LANGUAGES,
    "diller": SectionType.LANGUAGES,
    "certifications": SectionType.CERTIFICATIONS,
    "certificates": SectionType.CERTIFICATIONS,
    "sertifikalar": SectionType.CERTIFICATIONS,
    "projects": SectionType.PROJECTS,
    "project": SectionType.PROJECTS,
    "selected projects": SectionType.PROJECTS,
    "academic projects": SectionType.PROJECTS,
    "projeler": SectionType.PROJECTS,
    "publications": SectionType.PUBLICATIONS,
    "achievements": SectionType.ADDITIONAL,
    "accomplishments": SectionType.ADDITIONAL,
    "volunteer work": SectionType.ADDITIONAL,
    "yayınlar": SectionType.PUBLICATIONS,
}


def _looks_identity_like(value: str) -> bool:
    return "\n" not in value and 1 < len(value.split()) <= 5 and len(value) <= 80 and any(character.isalpha() for character in value)


def _looks_like_name(value: str) -> bool:
    words = value.split()
    normalized = value.casefold()
    return (
        _looks_identity_like(value)
        and 2 <= len(words) <= 4
        and not any(marker in normalized for marker in _NAME_EXCLUSIONS)
        and not any(word.casefold().endswith(_TITLE_SUFFIXES) for word in words)
        and all(word[:1].isupper() and word[1:].replace("-", "").isalpha() for word in words)
    )


def _looks_like_headline(value: str) -> bool:
    normalized = value.casefold().rstrip("s")
    return (
        _looks_identity_like(value)
        and not any(marker in normalized for marker in _NAME_EXCLUSIONS)
        and any(normalized.endswith(suffix) for suffix in _TITLE_SUFFIXES)
    )


class PDFParser:
    """Extracts text-based PDF source evidence without career interpretation."""

    def __init__(self, max_file_size: int = DEFAULT_MAX_PDF_BYTES, max_page_count: int = 50) -> None:
        if max_file_size <= 0 or max_page_count <= 0:
            raise ValueError("Maximum PDF file size must be greater than zero.")
        self._max_file_size = max_file_size
        self._max_page_count = max_page_count

    def parse(self, pdf_bytes: bytes, filename: str) -> CVDocument:
        self._validate_input(pdf_bytes, filename)
        try:
            document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception as error:
            raise InvalidPDFError("The supplied file is not a readable PDF.") from error

        try:
            if document.needs_pass:
                raise EncryptedPDFError("The PDF is password-protected and cannot be read.")
            if document.page_count > self._max_page_count:
                raise PDFPageLimitExceededError("The PDF exceeds the configured page limit.")

            blocks, pages = self._extract_pages(document)
            blocks = self._mark_repeated_contact_artifacts(blocks)
        except (EncryptedPDFError, NoMachineReadableTextError, PDFPageLimitExceededError):
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
            identity_evidence=self._identity_evidence(blocks),
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

    def _mark_repeated_contact_artifacts(self, blocks: list[DocumentBlock]) -> list[DocumentBlock]:
        """Keep first-page contact evidence but prevent repeated page furniture becoming facts."""
        grouped: dict[str, list[DocumentBlock]] = {}
        for block in blocks:
            if _CONTACT_PATTERN.search(block.raw_text):
                grouped.setdefault(" ".join(block.raw_text.casefold().split()), []).append(block)
        repeated = {
            block.stable_reference
            for group in grouped.values() if len({item.location.page_number for item in group}) > 1
            for block in group if block.location.page_number != 1
        }
        return [block.model_copy(update={"block_type": BlockType.UNKNOWN}) if block.stable_reference in repeated else block for block in blocks]

    def _extract_pages(
        self, document: pymupdf.Document
    ) -> tuple[list[DocumentBlock], list[DocumentPage]]:
        blocks: list[DocumentBlock] = []
        pages: list[DocumentPage] = []

        for page_number, page in enumerate(document, start=1):
            page_blocks, column_boundary = self._ordered_text_blocks(page)
            page_blocks = self._merge_bullet_continuations(page_blocks, column_boundary)
            page_references: list[str] = []
            block_index = 0
            for text_block in page_blocks:
                for raw_text in self._split_source_text(text_block[4]):
                    block = DocumentBlock(
                        raw_text=raw_text,
                        block_type=self._classify_block(raw_text, page_number, block_index),
                        location=SourceLocation(
                            page_number=page_number,
                            block_index=block_index,
                            x0=round(text_block[0], 3), y0=round(text_block[1], 3),
                            x1=round(text_block[2], 3), y1=round(text_block[3], 3),
                            reading_order=block_index,
                            column_index=(0 if column_boundary is None or text_block[0] < column_boundary else 1),
                        ),
                    )
                    blocks.append(block)
                    page_references.append(block.stable_reference)
                    block_index += 1
            pages.append(DocumentPage(page_number=page_number, block_references=tuple(page_references)))

        return blocks, pages

    def _merge_bullet_continuations(
        self, blocks: list[tuple[float, ...]], column_boundary: float | None
    ) -> list[tuple[float, ...]]:
        """Join only geometrically indented, adjacent continuation lines.

        A continuation must remain in the same detected column, start to the
        right of the bullet, and be no farther than two rendered line heights.
        This is a layout observation, not a career association.
        """
        merged: list[tuple[float, ...]] = []
        index = 0
        while index < len(blocks):
            current = list(blocks[index])
            if _BULLET_LINE_PATTERN.match(current[4]) and index + 1 < len(blocks):
                following = blocks[index + 1]
                same_column = column_boundary is None or (current[0] < column_boundary) == (following[0] < column_boundary)
                line_height = max(current[3] - current[1], following[3] - following[1])
                adjacent = 0 <= following[1] - current[3] <= line_height * 2
                indented = following[0] > current[0]
                if same_column and adjacent and indented and not _BULLET_LINE_PATTERN.match(following[4]):
                    current[2] = max(current[2], following[2])
                    current[3] = following[3]
                    current[4] = current[4].rstrip() + "\n" + following[4].lstrip()
                    merged.append(tuple(current))
                    index += 2
                    continue
            merged.append(tuple(current))
            index += 1
        return merged

    def _ordered_text_blocks(self, page: pymupdf.Page) -> tuple[list[tuple[float, ...]], float | None]:
        text_blocks = [
            block
            for block in page.get_text("blocks")
            if len(block) >= 5 and isinstance(block[4], str) and block[4].strip()
        ]
        if not text_blocks:
            return [], None

        column_boundary = self._column_boundary(text_blocks, page.rect.width)
        column_order = self._two_column_order(text_blocks, column_boundary)
        if column_order is not None:
            return column_order, column_boundary
        return sorted(text_blocks, key=self._top_left_key), None

    def _two_column_order(
        self, text_blocks: list[tuple[float, ...]], column_boundary: float | None
    ) -> list[tuple[float, ...]] | None:
        if column_boundary is None:
            return None
        left = [block for block in text_blocks if block[0] < column_boundary]
        right = [block for block in text_blocks if block[0] >= column_boundary]
        body_start = max(min(block[1] for block in left), min(block[1] for block in right))
        left_body = [block for block in left if block[1] >= body_start]
        right_body = [block for block in right if block[1] >= body_start]
        preamble = [block for block in text_blocks if block[1] < body_start]
        return (
            sorted(preamble, key=self._top_left_key)
            + sorted(left_body, key=self._top_left_key)
            + sorted(right_body, key=self._top_left_key)
        )

    def _column_boundary(
        self, text_blocks: list[tuple[float, ...]], page_width: float
    ) -> float | None:
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
        return column_boundary

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
        # PDF producers often combine a section label with the following body
        # into one text block (or put a short value after ``Label:``).  Keep
        # the original text, but expose the recognized heading as its own
        # canonical block so section ownership is not lost downstream.
        section_segments = self._split_inline_section_headings(lines)
        if section_segments is not None:
            return section_segments
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

    def _split_inline_section_headings(self, lines: tuple[str, ...]) -> tuple[str, ...] | None:
        segments: list[str] = []
        buffered: list[str] = []
        found = False

        def flush() -> None:
            if buffered and "".join(buffered).strip():
                segments.append("".join(buffered))
            buffered.clear()

        for line in lines:
            stripped = line.strip()
            normalized = self._normalized_heading(stripped)
            section_type = _SECTION_HEADINGS.get(normalized)
            if section_type is not None:
                flush()
                segments.append(line)
                found = True
                continue
            # A title-cased ``Project: ...`` line is a labelled project fact,
            # not a new PROJECTS section.  Only uppercase labels are reliable
            # inline section boundaries in this recovery path, except for the
            # conventional ``Languages: ...`` compact list form.
            if ":" in stripped:
                label, value = stripped.split(":", 1)
                label_section = _SECTION_HEADINGS.get(self._normalized_heading(label))
                if (label.strip().isupper() or label_section is SectionType.LANGUAGES) and label_section is not None and value.strip():
                    flush()
                    newline = "\n" if line.endswith("\n") else ""
                    segments.extend((f"{label.strip()}\n", f"{value.strip()}{newline}"))
                    found = True
                    continue
            buffered.append(line)
        flush()
        return tuple(segments) if found else None

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
            if block.block_type is BlockType.UNKNOWN:
                continue
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

    def _identity_evidence(self, blocks: Iterable[DocumentBlock]) -> tuple[IdentityEvidence, ...]:
        """Record conservative first-page header observations without claiming they are facts."""
        header: list[DocumentBlock] = []
        for block in blocks:
            if block.location.page_number != 1:
                continue
            if self._normalized_heading(block.raw_text) in _SECTION_HEADINGS:
                break
            if len(header) >= 6:
                break
            header.append(block)

        observations: list[IdentityEvidence] = []
        for block in header:
            for field, pattern in ((IdentityField.EMAIL, _EMAIL_VALUE_PATTERN), (IdentityField.PHONE, _PHONE_VALUE_PATTERN), (IdentityField.WEBSITE, _WEBSITE_VALUE_PATTERN)):
                for match in pattern.finditer(block.raw_text):
                    observations.append(IdentityEvidence(field=field, value=match.group(0), block_reference=block.stable_reference, confidence=ParserConfidence.HIGH, reason="unambiguous_header_contact"))

        text_blocks = [block for block in header if not _CONTACT_PATTERN.search(block.raw_text)]
        names = [(block, block.raw_text.strip()) for block in text_blocks if _looks_like_name(block.raw_text.strip())]
        if len(names) == 1:
            block, value = names[0]
            observations.append(IdentityEvidence(field=IdentityField.NAME, value=value, block_reference=block.stable_reference, confidence=ParserConfidence.HIGH, reason="unambiguous_first_page_header_name"))
        elif names:
            observations.extend(IdentityEvidence(field=IdentityField.NAME, value=value, block_reference=block.stable_reference, confidence=ParserConfidence.UNRESOLVED, reason="ambiguous_first_page_header_name") for block, value in names)
        elif text_blocks and _looks_identity_like(text_blocks[0].raw_text.strip()):
            observations.append(IdentityEvidence(field=IdentityField.NAME, value=text_blocks[0].raw_text.strip(), block_reference=text_blocks[0].stable_reference, confidence=ParserConfidence.UNRESOLVED, reason="ambiguous_header_name"))

        # A headline is only meaningful immediately below a single header name.  Do not
        # scan the remaining preamble: degree names and historical content can look like titles.
        headlines = []
        if len(names) == 1:
            name_block, _ = names[0]
            name_index = text_blocks.index(name_block)
            if name_index == 0 and len(text_blocks) > 1 and _looks_like_headline(text_blocks[1].raw_text.strip()):
                headlines.append((text_blocks[1], text_blocks[1].raw_text.strip()))
        if len(headlines) == 1:
            block, value = headlines[0]
            observations.append(IdentityEvidence(field=IdentityField.HEADLINE, value=value, block_reference=block.stable_reference, confidence=ParserConfidence.HIGH, reason="unambiguous_first_page_header_headline"))
        return tuple(observations)


def parse_pdf(
    pdf_bytes: bytes,
    filename: str,
    *,
    max_file_size: int = DEFAULT_MAX_PDF_BYTES,
    max_page_count: int = 50,
) -> CVDocument:
    """Parse PDF bytes into immutable source-document evidence."""

    return PDFParser(max_file_size=max_file_size, max_page_count=max_page_count).parse(pdf_bytes, filename)

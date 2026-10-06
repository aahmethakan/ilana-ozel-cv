"""Deterministic, public-projection-only PDF export."""

from textwrap import wrap

import pymupdf

from app.services.pdf_export.schemas import PdfExportValidationResult
from app.services.public_cv_projection import PublicCvProjection


class PdfExportError(ValueError):
    pass


_PAGE_WIDTH = 595
_PAGE_HEIGHT = 842
_LEFT = 54
_RIGHT = 54
_TOP = 54
_BOTTOM = 54
_BODY_SIZE = 10
_LINE_HEIGHT = 14
_FORBIDDEN_INTERNAL_MARKERS = (
    "session_id", "draft_id", "evidence_id", "atomic_evidence_id",
    "association_evidence_id", "work_candidate_id", "work_record_id",
    "source_type", "verification_status", "generation_plan",
)


def export_pdf(projection: PublicCvProjection) -> bytes:
    """Render the already-reviewed public projection as selectable PDF text."""
    review = projection.reviewed_draft.review
    if not (review.skills or review.work_entries or review.education):
        raise PdfExportError("Reviewed draft has no exportable content.")
    document = pymupdf.open()
    unicode_font = pymupdf.Font("cjk")
    page = document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.insert_font(fontname="F0", fontbuffer=unicode_font.buffer)
    cursor = _TOP

    def new_page() -> None:
        nonlocal page, cursor
        page = document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        page.insert_font(fontname="F0", fontbuffer=unicode_font.buffer)
        cursor = _TOP

    def lines(text: str, size: float) -> list[str]:
        width = max(24, int((_PAGE_WIDTH - _LEFT - _RIGHT) / (size * 0.54)))
        return wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [text]

    def write(text: str, *, size: float = _BODY_SIZE, bold: bool = False, gap_after: float = 0) -> None:
        nonlocal cursor
        for line in lines(text, size):
            if cursor + _LINE_HEIGHT > _PAGE_HEIGHT - _BOTTOM:
                new_page()
            # The built-in Helvetica fonts silently lose non-Latin public CV
            # text.  Embed PyMuPDF's portable universal font for every line.
            page.insert_text((_LEFT, cursor), line, fontsize=size, fontname="F0", color=(0, 0, 0))
            cursor += max(_LINE_HEIGHT, size * 1.35)
        cursor += gap_after

    if projection.name:
        write(projection.name, size=18, bold=True, gap_after=3)
    if projection.headline:
        write(projection.headline, size=11, gap_after=3)
    contact = " | ".join(value for value in (projection.contact.email, projection.contact.phone, projection.contact.website) if value)
    if contact:
        write(contact, size=9, gap_after=8)

    def heading(value: str) -> None:
        write(value, size=11, bold=True, gap_after=2)

    if projection.summary:
        heading("PROFESSIONAL SUMMARY")
        write(projection.summary, gap_after=6)
    if review.skills:
        heading("SKILLS")
        write(", ".join(dict.fromkeys(item.text for item in review.skills)), gap_after=6)
    if review.work_entries:
        heading("WORK EXPERIENCE")
        for entry in review.work_entries:
            write(" | ".join(value for value in (entry.title, entry.company) if value), bold=True)
            if entry.dates:
                write(entry.dates, size=9)
            for claim in entry.claims:
                write(f"- {claim.text}")
            cursor += 4
    if review.education:
        heading("EDUCATION")
        for entry in review.education:
            write(" | ".join(value for value in (entry.qualification, entry.institution) if value), bold=True)
            if entry.dates:
                write(entry.dates, size=9)
            cursor += 3

    data = document.tobytes(garbage=4, deflate=True)
    document.close()
    validate_pdf_export(data, projection)
    return data


def validate_pdf_export(data: bytes, projection: PublicCvProjection) -> PdfExportValidationResult:
    """Fail closed when the PDF is malformed, loses text, or leaks internals."""
    if not data or not data.startswith(b"%PDF-"):
        raise PdfExportError("PDF export is empty or invalid.")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
        page_count = document.page_count
        if page_count < 1:
            raise PdfExportError("PDF export has no pages.")
        text = "\n".join(page.get_text() for page in document)
        document.close()
    except PdfExportError:
        raise
    except Exception as error:
        raise PdfExportError("PDF structure is invalid.") from error
    if not text.strip():
        raise PdfExportError("PDF export has no selectable text layer.")
    if any(marker in text.lower() for marker in _FORBIDDEN_INTERNAL_MARKERS):
        raise PdfExportError("PDF contains internal metadata.")
    expected = [
        projection.name, projection.headline, projection.contact.email,
        projection.contact.phone, projection.contact.website, projection.summary,
        *(item.text for item in projection.reviewed_draft.review.skills),
        *(entry.company for entry in projection.reviewed_draft.review.work_entries),
        *(entry.title for entry in projection.reviewed_draft.review.work_entries),
        *(entry.institution for entry in projection.reviewed_draft.review.education),
    ]
    if any(value and value not in text for value in expected):
        raise PdfExportError("PDF did not preserve public projection content.")
    return PdfExportValidationResult(page_count=page_count, text=text)

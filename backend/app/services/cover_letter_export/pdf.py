from textwrap import wrap

import pymupdf

from app.services.public_cover_letter_projection import PublicCoverLetterProjection


class CoverLetterPdfExportError(ValueError):
    pass


_FORBIDDEN = ("session_id", "draft_id", "item_id", "evidence_id", "association_evidence_id", "atomic_evidence_id", "candidate_id", "work_record_id", "work_candidate_id", "verification_status", "source_type", "job_requirement_id", "match_id")


def export_cover_letter_pdf(projection: PublicCoverLetterProjection) -> bytes:
    if not (projection.opening.strip() and projection.closing.strip()):
        raise CoverLetterPdfExportError("Cover letter has no exportable content.")
    document = pymupdf.open(); unicode_font = pymupdf.Font("cjk"); page = document.new_page(width=595, height=842); page.insert_font(fontname="F0", fontbuffer=unicode_font.buffer); cursor = 54
    def write(text: str, size: int = 10, bold: bool = False, gap: int = 4) -> None:
        nonlocal page, cursor
        width = max(24, int(487 / (size * .54)))
        for line in wrap(text, width=width, break_long_words=False) or [text]:
            if cursor + 15 > 788:
                page = document.new_page(width=595, height=842); page.insert_font(fontname="F0", fontbuffer=unicode_font.buffer); cursor = 54
            page.insert_text((54, cursor), line, fontsize=size, fontname="F0", color=(0, 0, 0)); cursor += max(15, int(size * 1.35))
        cursor += gap
    if projection.candidate_name: write(projection.candidate_name, 14, True)
    contact = " | ".join(value for value in (projection.contact.email, projection.contact.phone, projection.contact.website) if value)
    if contact: write(contact, 9, gap=8)
    if projection.target_role: write(f"Application for {projection.target_role}" + (f" at {projection.target_company}" if projection.target_company else ""), 10, True, 8)
    write("Dear Hiring Manager,", gap=8); write(projection.opening, gap=8)
    for paragraph in projection.body_sections: write(paragraph, gap=8)
    write(projection.closing, gap=8); write("Kind regards,", gap=2)
    if projection.candidate_name: write(projection.candidate_name)
    data = document.tobytes(garbage=4, deflate=True); document.close()
    validate_cover_letter_pdf(data, projection)
    return data


def validate_cover_letter_pdf(data: bytes, projection: PublicCoverLetterProjection) -> None:
    if not data.startswith(b"%PDF-"):
        raise CoverLetterPdfExportError("PDF is invalid.")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
        if document.page_count < 1: raise CoverLetterPdfExportError("PDF has no pages.")
        text = "\n".join(page.get_text() for page in document); document.close()
    except CoverLetterPdfExportError: raise
    except Exception as error: raise CoverLetterPdfExportError("PDF structure is invalid.") from error
    if not text.strip() or any(value in text.lower() for value in _FORBIDDEN):
        raise CoverLetterPdfExportError("PDF is empty or contains internal metadata.")
    for value in (projection.candidate_name, projection.target_role, projection.target_company, projection.opening, *projection.body_sections, projection.closing):
        if value and value not in text: raise CoverLetterPdfExportError("PDF did not preserve reviewed public content.")

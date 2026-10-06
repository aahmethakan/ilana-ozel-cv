from io import BytesIO
from zipfile import ZipFile

import pymupdf

from app.services.cover_letter_export import export_cover_letter_docx, export_cover_letter_pdf
from app.services.public_cover_letter_projection.service import PublicCoverLetterContact, PublicCoverLetterProjection


def test_cover_letter_exporters_consume_complete_public_projection_only() -> None:
    projection = PublicCoverLetterProjection(
        candidate_name="Örnek Aday",
        contact=PublicCoverLetterContact(email="candidate@example.com", phone="5551234567"),
        target_role="Mechanical Engineer", target_company="ABC Engineering",
        opening="I am applying for the Mechanical Engineer position at ABC Engineering.",
        body_sections=("Relevant experience evidence: Supported machine installation activities.", "Relevant skill evidence: PLC systems."),
        closing="Thank you for considering my application.",
    )
    docx = export_cover_letter_docx(projection)
    pdf = export_cover_letter_pdf(projection)
    with ZipFile(BytesIO(docx)) as archive:
        docx_text = archive.read("word/document.xml").decode("utf-8")
    document = pymupdf.open(stream=pdf, filetype="pdf")
    assert document.page_count >= 1
    pdf_text = "\n".join(page.get_text() for page in document); document.close()
    for text in ("Örnek Aday", "candidate@example.com", "Mechanical Engineer", "ABC Engineering", "Supported machine installation activities.", "PLC systems."):
        assert text in docx_text and text in pdf_text
    assert "session_id" not in docx_text and "session_id" not in pdf_text

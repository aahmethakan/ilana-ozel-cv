"""Anonymous regression shape for a real multi-role, single-company CV."""

import asyncio

import httpx
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
from app.extraction.career import extract_career_profile
from app.main import app
from app.parsers.pdf import parse_pdf


def _anonymous_supply_chain_cv() -> CVDocument:
    rows = [
        ("WORK EXPERIENCE", BlockType.HEADING),
        ("Supply Chain Planning Intern", BlockType.PARAGRAPH),
        ("Example Retail", BlockType.PARAGRAPH),
        ("May 2022 - August 2022", BlockType.PARAGRAPH),
        ("- Supported demand planning", BlockType.BULLET),
        ("Supply Chain Planning Specialist", BlockType.PARAGRAPH),
        ("Example Retail", BlockType.PARAGRAPH),
        ("August 2022 - August 2024", BlockType.PARAGRAPH),
        ("- Improved availability reporting", BlockType.BULLET),
        ("Supply Chain Planning Executive", BlockType.PARAGRAPH),
        ("Example Retail", BlockType.PARAGRAPH),
        ("August 2024 - Present", BlockType.PARAGRAPH),
        ("- Supply planning based on forecast, availability, sales, volume and waste", BlockType.BULLET),
        ("- Operation management", BlockType.BULLET),
        ("- Working on diverse supply chain projects", BlockType.BULLET),
        ("- Project Follow-up", BlockType.BULLET),
        ("- Supplier relations and demand management", BlockType.BULLET),
        ("SKILLS", BlockType.HEADING),
        ("SAP", BlockType.PARAGRAPH),
        ("Relex", BlockType.PARAGRAPH),
        ("MS Office Excel", BlockType.PARAGRAPH),
        ("Power BI", BlockType.PARAGRAPH),
    ]
    blocks = tuple(
        DocumentBlock(raw_text=text, block_type=kind, location=SourceLocation(page_number=1, block_index=index))
        for index, (text, kind) in enumerate(rows)
    )
    experience_end = next(index for index, block in enumerate(blocks) if block.raw_text == "SKILLS")
    return CVDocument(
        source=DocumentSource(filename="anonymous-supply-chain.pdf", document_format=DocumentFormat.PDF, page_count=1),
        blocks=blocks,
        pages=(DocumentPage(page_number=1, block_references=tuple(block.stable_reference for block in blocks)),),
        sections=(
            CVSection(section_type=SectionType.EXPERIENCE, original_heading="WORK EXPERIENCE", block_references=tuple(block.stable_reference for block in blocks[:experience_end])),
            CVSection(section_type=SectionType.SKILLS, original_heading="SKILLS", block_references=tuple(block.stable_reference for block in blocks[experience_end:])),
        ),
    )


def test_anonymous_multi_role_company_cv_preserves_record_boundaries_and_facts() -> None:
    profile = extract_career_profile(_anonymous_supply_chain_cv()).profile

    assert [(item.company, item.title) for item in profile.work_experiences] == [
        ("Example Retail", "Supply Chain Planning Intern"),
        ("Example Retail", "Supply Chain Planning Specialist"),
        ("Example Retail", "Supply Chain Planning Executive"),
    ]
    assert [item.start_date.month for item in profile.work_experiences] == [5, 8, 8]
    assert [item.end_date.month if item.end_date else None for item in profile.work_experiences] == [8, 8, None]
    assert [item.is_current for item in profile.work_experiences] == [False, False, True]
    assert [fact.statement for fact in profile.work_experiences[0].facts] == ["Supported demand planning"]
    assert [fact.statement for fact in profile.work_experiences[1].facts] == ["Improved availability reporting"]
    assert [fact.statement for fact in profile.work_experiences[2].facts] == [
        "Supply planning based on forecast, availability, sales, volume and waste",
        "Operation management",
        "Working on diverse supply chain projects",
        "Project Follow-up",
        "Supplier relations and demand management",
    ]


def test_generic_project_words_and_standalone_skills_do_not_create_unsafe_entities_or_associations() -> None:
    profile = extract_career_profile(_anonymous_supply_chain_cv()).profile

    assert profile.projects == ()
    assert [fact.statement for fact in profile.skills] == ["SAP", "Relex", "MS Office Excel", "Power BI"]
    executive_facts = {fact.statement for fact in profile.work_experiences[2].facts}
    assert "SAP" not in executive_facts and "Relex" not in executive_facts


def test_pdf_parser_document_order_supports_anonymous_multi_role_shape() -> None:
    profile = extract_career_profile(parse_pdf(_anonymous_pdf(), "anonymous-supply-chain.pdf")).profile

    assert [item.title for item in profile.work_experiences] == [
        "Supply Chain Planning Intern",
        "Supply Chain Planning Specialist",
        "Supply Chain Planning Executive",
    ]
    assert profile.projects == ()


def _anonymous_pdf() -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "candidate@example.com", fontsize=10)
    for index, block in enumerate(_anonymous_supply_chain_cv().blocks, start=1):
        page.insert_text((72, 72 + index * 18), block.raw_text, fontsize=10)
    data = pdf.tobytes()
    pdf.close()
    return data


def test_anonymous_multi_role_pdf_keeps_job_keywords_out_of_generation_and_export() -> None:
    async def request(method: str, path: str, **kwargs) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    analysis = asyncio.run(request("POST", "/api/v1/cv/analyze", files={
        "file": ("anonymous-supply-chain.pdf", _anonymous_pdf(), "application/pdf"),
    }))
    assert analysis.status_code == 200
    session_id = analysis.json()["session_id"]
    assert [item["title"] for item in analysis.json()["profile"]["work_experiences"]] == [
        "Supply Chain Planning Intern", "Supply Chain Planning Specialist", "Supply Chain Planning Executive",
    ]

    job = asyncio.run(request("POST", "/api/v1/jobs/analyze", json={
        "session_id": session_id,
        "job_text": "Job Title: Supply Chain Planner\nSkills\n- SAP\n- Power BI\n- Python",
    }))
    assert job.status_code == 200
    assert "Python" not in {item["statement"] for item in analysis.json()["profile"]["skills"]}

    review = asyncio.run(request("POST", "/api/v1/cv/generate/review", json={"session_id": session_id, "mode": "targeted"}))
    assert review.status_code == 200
    assert "Python" not in str(review.json())
    draft_id = review.json()["draft_id"]
    for path in ("/api/v1/cv/generate/export/docx", "/api/v1/cv/generate/export/pdf"):
        exported = asyncio.run(request("POST", path, json={"session_id": session_id, "draft_id": draft_id}))
        assert exported.status_code == 200

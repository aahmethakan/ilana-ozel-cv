import asyncio
from io import BytesIO
from zipfile import ZipFile

import httpx
import pymupdf

from app.main import app
from app.api.routes.cv import session_store
from app.services.public_cv_projection import build_public_cv_projection
from app.services.public_cv_projection.service import PublicCvContact, PublicCvProjection
from app.services.draft_review import ReviewedCvDraft
from app.services.generation_review import DraftReviewClaim, DraftReviewEducationEntry, DraftReviewWorkEntry, GeneratedCvDraftReview
from app.services.generation_strategy import GenerationMode
from app.services.docx_export import export_reviewed_draft
from app.services.pdf_export import export_pdf, validate_pdf_export
from app.services.generation_orchestration import generate_deterministic_cv
from app.services.generation_review import build_generated_cv_review
from app.services.generation_strategy import GenerationTargetSection, build_generation_plan
from tests.test_work_fact_association_claim_validation import associated_context


def _pdf(*lines: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 24), line)
    data = document.tobytes()
    document.close()
    return data


async def _request(method: str, path: str, **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def _analyze_ready_cv() -> str:
    response = asyncio.run(_request(
        "POST",
        "/api/v1/cv/analyze",
        files={"file": ("ready.pdf", _pdf("candidate@example.com", "SKILLS", "- SAP"), "application/pdf")},
    ))
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _review(session_id: str, mode: str, **extra: object) -> httpx.Response:
    return asyncio.run(_request(
        "POST",
        "/api/v1/cv/generate/review",
        json={"session_id": session_id, "mode": mode, **extra},
    ))


def test_general_generation_review_is_public_deterministic_and_requires_no_job() -> None:
    session_id = _analyze_ready_cv()

    first = _review(session_id, "general")
    second = _review(session_id, "general")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["review"] == {
        "mode": "general",
        "skills": [{"text": "SAP", "source": "verified_evidence"}],
        "work_entries": [],
        "education": [],
    }
    assert first.json()["draft_id"].startswith("draft:")
    assert first.json()["items"][0]["decision"] == "keep"
    assert not ({"plan", "draft", "atomic_evidence_id", "rendered_claim_id"} & set(first.json()["review"]))


def test_targeted_generation_requires_current_job_and_uses_server_side_match() -> None:
    session_id = _analyze_ready_cv()

    missing = _review(session_id, "targeted")
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "targeted_job_state_missing"

    job = asyncio.run(_request("POST", "/api/v1/jobs/analyze", json={
        "session_id": session_id,
        "job_text": "Job Title: Engineer\nSkills\n- SAP",
    }))
    assert job.status_code == 200
    first = _review(session_id, "targeted")
    second = _review(session_id, "targeted")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["review"] == {
        "mode": "targeted",
        "skills": [{"text": "SAP", "source": "verified_evidence"}],
        "work_entries": [],
        "education": [],
    }


def test_generation_rejects_missing_or_stale_context_and_caller_generation_injection() -> None:
    missing = _review("missing", "general")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "analysis_session_not_found"

    session_id = _analyze_ready_cv()
    injected = _review(session_id, "general", plan={"selections": [{"claim": "injected"}]})
    assert injected.status_code == 422

    analysis = asyncio.run(_request(
        "POST", "/api/v1/cv/analyze",
        files={"file": ("needs-review.pdf", _pdf("candidate@example.com", "SKILLS", "Experienced with SAP and Oracle."), "application/pdf")},
    ))
    assert analysis.status_code == 200
    blocked = _review(analysis.json()["session_id"], "general")
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] in {
        "generation_readiness_blocked",
        "generation_readiness_needs_review",
    }


def test_unaccepted_coach_answer_preserves_generation_context_without_promoting_candidate() -> None:
    session_id = _analyze_ready_cv()
    analysis_session = asyncio.run(_request(
        "POST",
        "/api/v1/cv/analyze",
        files={"file": ("coach.pdf", _pdf("candidate@example.com", "SKILLS", "- SAP"), "application/pdf")},
    )).json()
    question = next(item for item in analysis_session["coach"]["questions"] if item["category"] == "certification")
    answer = asyncio.run(_request("POST", "/api/v1/cv/coach-answer", json={
        "session_id": analysis_session["session_id"],
        "question_id": question["question_id"],
        "answer_text": "PMP",
    }))
    assert answer.status_code == 200
    review = _review(analysis_session["session_id"], "general")
    assert review.status_code == 200
    assert "PMP" not in {item["text"] for item in review.json()["items"]}
    assert _review(session_id, "general").status_code == 200


def test_general_associated_evidence_composes_a_public_work_entry() -> None:
    context = associated_context()
    plan = build_generation_plan(context)

    assert [item.target_section for item in plan.selections] == [GenerationTargetSection.WORK_EXPERIENCE]
    review = build_generated_cv_review(generate_deterministic_cv(context, plan))
    assert review.skills == ()
    assert len(review.work_entries) == 1
    assert review.work_entries[0].claims[0].text == "SAP"


def test_draft_decisions_remove_undo_and_reject_stale_or_unknown_items() -> None:
    session_id = _analyze_ready_cv()
    generated = _review(session_id, "general").json()
    item_id = generated["items"][0]["item_id"]

    removed = asyncio.run(_request("POST", "/api/v1/cv/generate/review/decision", json={
        "session_id": session_id, "draft_id": generated["draft_id"], "item_id": item_id, "decision": "remove",
    }))
    assert removed.status_code == 200
    assert removed.json()["review"]["skills"] == []
    assert next(item for item in removed.json()["items"] if item["item_id"] == item_id)["decision"] == "remove"

    restored = asyncio.run(_request("POST", "/api/v1/cv/generate/review/decision", json={
        "session_id": session_id, "draft_id": generated["draft_id"], "item_id": item_id, "decision": "keep",
    }))
    assert restored.status_code == 200
    assert restored.json()["review"]["skills"][0]["text"] == "SAP"

    stale = asyncio.run(_request("POST", "/api/v1/cv/generate/review/decision", json={
        "session_id": session_id, "draft_id": "draft:fake", "item_id": item_id, "decision": "remove",
    }))
    assert stale.status_code == 409
    unknown = asyncio.run(_request("POST", "/api/v1/cv/generate/review/decision", json={
        "session_id": session_id, "draft_id": generated["draft_id"], "item_id": "rendered:fake", "decision": "remove",
    }))
    assert unknown.status_code == 422


def test_draft_session_mismatch_returns_the_same_safe_stale_contract() -> None:
    first_session = _analyze_ready_cv()
    second = asyncio.run(_request(
        "POST",
        "/api/v1/cv/analyze",
        files={"file": ("other.pdf", _pdf("other@example.com", "SKILLS", "- Python"), "application/pdf")},
    ))
    second_draft = _review(second.json()["session_id"], "general").json()["draft_id"]

    mismatch = asyncio.run(_request("POST", "/api/v1/cv/generate/export/pdf", json={
        "session_id": first_session, "draft_id": second_draft,
    }))
    assert mismatch.status_code == 409
    assert mismatch.json() == {"error": {"code": "stale_draft", "message": "Generate the current CV draft again before exporting."}}
    assert second_draft not in mismatch.text


def test_docx_export_download_uses_current_reviewed_draft_only() -> None:
    session_id = _analyze_ready_cv()
    generated = _review(session_id, "general").json()
    download = asyncio.run(_request("POST", "/api/v1/cv/generate/export/docx", json={
        "session_id": session_id, "draft_id": generated["draft_id"],
    }))
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert download.content[:2] == b"PK"
    stale = asyncio.run(_request("POST", "/api/v1/cv/generate/export/docx", json={
        "session_id": session_id, "draft_id": "draft:fake",
    }))
    assert stale.status_code == 409


def test_public_projection_keeps_only_authoritative_optional_contact_fields() -> None:
    session_id = _analyze_ready_cv()
    generated = _review(session_id, "general").json()
    session = session_store.get(session_id)
    projection = build_public_cv_projection(
        profile=session.profile,
        reviewed_draft=__import__("app.services.draft_review", fromlist=["reviewed_draft"]).reviewed_draft(session.current_generated_draft),
    )
    assert generated["draft_id"] == projection.reviewed_draft.draft_id
    assert projection.contact.email == "candidate@example.com"
    assert projection.contact.phone is None
    assert projection.summary is None


def test_pdf_export_endpoint_has_selectable_text_and_rejects_stale_and_injected_content() -> None:
    session_id = _analyze_ready_cv()
    generated = _review(session_id, "general").json()
    download = asyncio.run(_request("POST", "/api/v1/cv/generate/export/pdf", json={
        "session_id": session_id, "draft_id": generated["draft_id"],
    }))
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.headers["content-disposition"] == 'attachment; filename="CV.pdf"'
    assert download.content.startswith(b"%PDF-")
    pdf = pymupdf.open(stream=download.content, filetype="pdf")
    text = "\n".join(page.get_text() for page in pdf)
    pdf.close()
    assert "SKILLS" in text and "SAP" in text
    assert session_id not in text and generated["draft_id"] not in text

    injected = asyncio.run(_request("POST", "/api/v1/cv/generate/export/pdf", json={
        "session_id": session_id, "draft_id": generated["draft_id"], "name": "Injected Candidate",
    }))
    assert injected.status_code == 422
    stale = asyncio.run(_request("POST", "/api/v1/cv/generate/export/pdf", json={
        "session_id": session_id, "draft_id": "draft:fake",
    }))
    assert stale.status_code == 409
    missing = asyncio.run(_request("POST", "/api/v1/cv/generate/export/pdf", json={
        "session_id": "missing", "draft_id": generated["draft_id"],
    }))
    assert missing.status_code == 404


def test_targeted_pdf_export_uses_the_current_server_side_job_state() -> None:
    session_id = _analyze_ready_cv()
    job = asyncio.run(_request("POST", "/api/v1/jobs/analyze", json={
        "session_id": session_id,
        "job_text": "Job Title: Senior Project Engineer\nSkills\n- SAP",
    }))
    assert job.status_code == 200
    generated = _review(session_id, "targeted").json()
    exported = asyncio.run(_request("POST", "/api/v1/cv/generate/export/pdf", json={
        "session_id": session_id, "draft_id": generated["draft_id"],
    }))
    assert exported.status_code == 200
    text = "\n".join(page.get_text() for page in pymupdf.open(stream=exported.content, filetype="pdf"))
    assert "SAP" in text
    assert "Senior Project Engineer" not in text


def test_validation_endpoint_is_read_only_deterministic_and_rejects_caller_content() -> None:
    session_id = _analyze_ready_cv()
    generated = _review(session_id, "general").json()
    payload = {"session_id": session_id, "draft_id": generated["draft_id"]}
    first = asyncio.run(_request("POST", "/api/v1/cv/generate/validate", json=payload))
    second = asyncio.run(_request("POST", "/api/v1/cv/generate/validate", json=payload))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["overall_status"] == "WARNING"
    assert {item["validator"] for item in first.json()["validators"]} == {"FACT", "CONSISTENCY", "ATS", "FORMAT", "LANGUAGE"}
    assert not ({"session_id", "draft_id", "evidence_id", "source_type"} & set(first.json()))
    session = session_store.get(session_id)
    before = session.current_generated_draft.model_dump(mode="json"), session.draft_decisions.copy(), session.draft_rewrites.copy()
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/validate", json={**payload, "projection": {"name": "Injected"}})).status_code == 422
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/validate", json={**payload, "severity": "PASS"})).status_code == 422
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/validate", json={"session_id": session_id, "draft_id": "draft:stale"})).status_code == 409
    after = session.current_generated_draft.model_dump(mode="json"), session.draft_decisions.copy(), session.draft_rewrites.copy()
    assert before == after


def test_quality_endpoint_uses_current_reviewed_state_and_rejects_injection() -> None:
    session_id = _analyze_ready_cv()
    generated = _review(session_id, "general").json()
    payload = {"session_id": session_id, "draft_id": generated["draft_id"]}
    first = asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json=payload))
    second = asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json=payload))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert {item["name"] for item in first.json()["dimensions"]} == {"completeness", "evidence", "structure", "ats_readiness"}
    assert not ({"session_id", "draft_id", "evidence_id", "source_type"} & set(first.json()))
    item_id = generated["items"][0]["item_id"]
    removed = asyncio.run(_request("POST", "/api/v1/cv/generate/review/decision", json={
        **payload, "item_id": item_id, "decision": "remove",
    }))
    assert removed.status_code == 200
    removed_quality = asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json=payload))
    assert removed_quality.status_code == 200
    assert removed_quality.json()["score"] < first.json()["score"]
    restored = asyncio.run(_request("POST", "/api/v1/cv/generate/review/decision", json={
        **payload, "item_id": item_id, "decision": "keep",
    }))
    assert restored.status_code == 200
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json=payload)).json() == first.json()
    for field in ("score", "projection", "dimensions", "recommendations"):
        assert asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json={**payload, field: "injected"})).status_code == 422
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json={"session_id": session_id, "draft_id": "draft:stale"})).status_code == 409


def test_targeted_job_state_does_not_change_quality_for_the_same_reviewed_content() -> None:
    session_id = _analyze_ready_cv()
    general = _review(session_id, "general").json()
    general_quality = asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json={"session_id": session_id, "draft_id": general["draft_id"]}))
    job = asyncio.run(_request("POST", "/api/v1/jobs/analyze", json={
        "session_id": session_id, "job_text": "Job Title: Senior Engineer\nSkills\n- SAP",
    }))
    assert job.status_code == 200
    targeted = _review(session_id, "targeted").json()
    targeted_quality = asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json={"session_id": session_id, "draft_id": targeted["draft_id"]}))
    assert targeted_quality.status_code == 200
    assert targeted_quality.json() == general_quality.json()


def test_targeted_cover_letter_is_fact_safe_reviewable_and_strict() -> None:
    session_id = _analyze_ready_cv()
    missing = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"}))
    assert missing.status_code == 409
    job = asyncio.run(_request("POST", "/api/v1/jobs/analyze", json={
        "session_id": session_id, "job_text": "Job Title: Senior Project Engineer\nCompany: ABC Engineering\nSkills\n- SAP\n- Siemens PLC",
    }))
    assert job.status_code == 200
    first = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"}))
    second = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"}))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    letter = first.json()
    assert letter["target_role"] == "Senior Project Engineer"
    assert letter["target_company"] == "ABC Engineering"
    assert "Senior Project Engineer position" in letter["opening"]
    assert "Siemens" not in " ".join(letter["body_sections"])
    assert "SAP" in " ".join(letter["body_sections"])
    assert not ({"session_id", "evidence_id", "source_type", "candidate_id"} & set(letter))
    item_id = letter["items"][0]["item_id"]
    removed = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/decision", json={
        "session_id": session_id, "draft_id": letter["draft_id"], "item_id": item_id, "decision": "remove",
    }))
    assert removed.status_code == 200 and "SAP" not in " ".join(removed.json()["body_sections"])
    restored = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/decision", json={
        "session_id": session_id, "draft_id": letter["draft_id"], "item_id": item_id, "decision": "keep",
    }))
    assert restored.status_code == 200 and "SAP" in " ".join(restored.json()["body_sections"])
    fallback = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/rewrite", json={
        "session_id": session_id, "draft_id": letter["draft_id"], "item_id": item_id,
    }))
    assert fallback.status_code == 200
    rewrite = next(item["rewrite"] for item in fallback.json()["items"] if item["item_id"] == item_id)
    assert rewrite["rewritten_text"] == "SAP" and rewrite["final_status"] == "rejected"
    removed_again = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/decision", json={
        "session_id": session_id, "draft_id": letter["draft_id"], "item_id": item_id, "decision": "remove",
    }))
    assert removed_again.status_code == 200
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/rewrite", json={
        "session_id": session_id, "draft_id": letter["draft_id"], "item_id": item_id,
    })).status_code == 422
    for field in ("original_text", "rewritten_text", "claim", "evidence", "company", "role", "motivation"):
        assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/rewrite", json={
            "session_id": session_id, "draft_id": letter["draft_id"], "item_id": item_id, field: "injected",
        })).status_code == 422
    regenerated = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"}))
    assert regenerated.status_code == 200
    assert regenerated.json()["draft_id"] == letter["draft_id"]
    assert next(item for item in regenerated.json()["items"] if item["item_id"] == item_id)["rewrite"] is None


def test_cover_letter_docx_pdf_exports_use_only_current_reviewed_public_state() -> None:
    session_id = _analyze_ready_cv()
    job = asyncio.run(_request("POST", "/api/v1/jobs/analyze", json={
        "session_id": session_id, "job_text": "Job Title: Senior Project Engineer\nCompany: ABC Engineering\nSkills\n- SAP\n- Siemens PLC",
    }))
    assert job.status_code == 200
    letter = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"})).json()
    payload = {"session_id": session_id, "draft_id": letter["draft_id"]}
    docx = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/export/docx", json=payload))
    pdf = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/export/pdf", json=payload))
    assert docx.status_code == pdf.status_code == 200
    assert docx.headers["content-disposition"] == 'attachment; filename="Cover_Letter.docx"'
    assert pdf.headers["content-disposition"] == 'attachment; filename="Cover_Letter.pdf"'
    with ZipFile(BytesIO(docx.content)) as archive:
        docx_text = archive.read("word/document.xml").decode("utf-8")
    pdf_document = pymupdf.open(stream=pdf.content, filetype="pdf")
    pdf_text = "\n".join(page.get_text() for page in pdf_document); pdf_document.close()
    for value in ("Senior Project Engineer", "ABC Engineering", letter["opening"], letter["closing"], "SAP"):
        assert value in docx_text and value in pdf_text
    for internal in (session_id, letter["draft_id"], "evidence_id", "association_evidence_id", "item_id"):
        assert internal not in docx_text and internal not in pdf_text
    item_id = letter["items"][0]["item_id"]
    removed = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/decision", json={**payload, "item_id": item_id, "decision": "remove"}))
    assert removed.status_code == 200
    removed_pdf = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/export/pdf", json=payload))
    removed_text = "\n".join(page.get_text() for page in pymupdf.open(stream=removed_pdf.content, filetype="pdf"))
    assert "SAP" not in removed_text
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/decision", json={**payload, "item_id": item_id, "decision": "keep"})).status_code == 200
    assert "SAP" in "\n".join(page.get_text() for page in pymupdf.open(stream=asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/export/pdf", json=payload)).content, filetype="pdf"))
    for field in ("text", "opening", "closing", "role", "company", "claims", "evidence", "rewritten_text"):
        assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/export/pdf", json={**payload, field: "injected"})).status_code == 422
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/export/docx", json={"session_id": session_id, "draft_id": "cover-letter:stale"})).status_code == 409
    for field in ("text", "claims", "company", "target_role", "motivation", "evidence"):
        assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted", field: "injected"})).status_code == 422
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "general"})).status_code == 422
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/decision", json={
        "session_id": session_id, "draft_id": letter["draft_id"], "item_id": "cover-item:fake", "decision": "remove",
    })).status_code == 422


def test_pdf_export_respects_review_remove_and_undo() -> None:
    response = asyncio.run(_request(
        "POST",
        "/api/v1/cv/analyze",
        files={"file": ("two-skills.pdf", _pdf("candidate@example.com", "SKILLS", "- SAP", "- Oracle"), "application/pdf")},
    ))
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    generated = _review(session_id, "general").json()
    item_id = generated["items"][0]["item_id"]
    for decision, expected in (("remove", False), ("keep", True)):
        decided = asyncio.run(_request("POST", "/api/v1/cv/generate/review/decision", json={
            "session_id": session_id, "draft_id": generated["draft_id"], "item_id": item_id, "decision": decision,
        }))
        assert decided.status_code == 200
        exported = asyncio.run(_request("POST", "/api/v1/cv/generate/export/pdf", json={
            "session_id": session_id, "draft_id": generated["draft_id"],
        }))
        assert exported.status_code == 200
        text = "\n".join(page.get_text() for page in pymupdf.open(stream=exported.content, filetype="pdf"))
        assert ("SAP" in text) is expected
        assert "Oracle" in text


def test_pdf_and_docx_export_share_the_complete_public_projection() -> None:
    review = GeneratedCvDraftReview(
        mode=GenerationMode.GENERAL,
        skills=(DraftReviewClaim(text="SAP", source="verified_evidence"),),
        work_entries=(DraftReviewWorkEntry(company="Acme", title="Mechanical Engineer", dates="2020 - 2024", claims=(DraftReviewClaim(text="Maintained machinery", source="verified_associated_evidence"),)),),
        education=(DraftReviewEducationEntry(institution="Technical University", qualification="BSc Engineering", dates="2016 - 2020"),),
    )
    projection = PublicCvProjection(
        name="Örnek Aday", headline="Mechanical Engineer", contact=PublicCvContact(email="candidate@example.com"),
        summary="İş özeti.",
        reviewed_draft=ReviewedCvDraft(draft_id="draft:internal-not-exported", review=review),
    )
    pdf = export_pdf(projection)
    pdf_text = validate_pdf_export(pdf, projection).text
    docx = export_reviewed_draft(projection)
    with ZipFile(BytesIO(docx)) as archive:
        docx_text = archive.read("word/document.xml").decode("utf-8")
    for public_value in ("Örnek Aday", "Mechanical Engineer", "candidate@example.com", "İş özeti.", "SAP", "Acme", "Technical University"):
        assert public_value in pdf_text
        assert public_value in docx_text
    assert "draft:internal-not-exported" not in pdf_text

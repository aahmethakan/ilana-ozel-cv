import asyncio
import shutil
import subprocess
from pathlib import Path

import httpx
import pymupdf

from app.api.routes.cv import session_store
from app.core.config import get_settings
from app.main import app
from app.parsers.pdf import DEFAULT_MAX_PDF_BYTES
from app.services.analysis_session import AnalysisSessionStore
from app.services.analysis_session.persistence import SQLiteSessionPersistence


async def post_parse(files: dict[str, tuple[str, bytes, str]] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/cv/parse", files=files)


async def cors_preflight() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.options(
            "/api/v1/cv/parse",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )


async def request(method: str, path: str, **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def text_pdf(*lines: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + (index * 24)), line)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def page_pdf(page_count: int) -> bytes:
    document = pymupdf.open()
    for _ in range(page_count):
        document.new_page().insert_text((72, 72), "SKILLS\nSAP")
    data = document.tobytes(); document.close()
    return data


def test_parse_endpoint_returns_safe_summary_for_text_pdf() -> None:
    response = asyncio.run(
        post_parse(
            {
                "file": (
                    "candidate.pdf",
                    text_pdf("WORK EXPERIENCE", "Commissioned production lines"),
                    "application/pdf",
                )
            }
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "parsed",
        "filename": "candidate.pdf",
        "page_count": 1,
        "block_count": 2,
        "sections": [
            {
                "type": "experience",
                "original_heading": "WORK EXPERIENCE",
                "block_count": 2,
            }
        ],
    }


def test_parse_endpoint_rejects_pdf_over_configured_page_limit_before_extraction() -> None:
    response = asyncio.run(post_parse({"file": ("many-pages.pdf", page_pdf(get_settings().pdf_max_pages + 1), "application/pdf")}))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pdf_page_limit_exceeded"


def test_parse_endpoint_rejects_missing_file() -> None:
    response = asyncio.run(post_parse())

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "missing_file", "message": "A PDF file is required."}
    }


def test_parse_endpoint_rejects_non_pdf_upload() -> None:
    response = asyncio.run(post_parse({"file": ("notes.txt", b"plain text", "text/plain")}))

    assert response.status_code == 415
    assert response.json() == {
        "error": {"code": "unsupported_file_type", "message": "Only PDF files are supported."}
    }


def test_parse_endpoint_rejects_empty_pdf() -> None:
    response = asyncio.run(post_parse({"file": ("empty.pdf", b"", "application/pdf")}))

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "empty_pdf", "message": "The PDF file is empty."}}


def test_parse_endpoint_rejects_invalid_pdf() -> None:
    response = asyncio.run(post_parse({"file": ("invalid.pdf", b"not a PDF", "application/pdf")}))

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_pdf",
            "message": "The file could not be read as a valid PDF.",
        }
    }


def test_parse_endpoint_rejects_textless_pdf() -> None:
    document = pymupdf.open()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()

    response = asyncio.run(post_parse({"file": ("scanned.pdf", pdf_bytes, "application/pdf")}))

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "no_machine_readable_text",
            "message": "No machine-readable text was found in the PDF.",
        }
    }


def test_parse_endpoint_rejects_encrypted_pdf() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Protected source text")
    pdf_bytes = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    document.close()

    response = asyncio.run(post_parse({"file": ("protected.pdf", pdf_bytes, "application/pdf")}))

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "encrypted_pdf",
            "message": "Password-protected PDFs are not supported.",
        }
    }


def test_parse_endpoint_rejects_oversized_pdf_before_parsing() -> None:
    response = asyncio.run(
        post_parse(
            {
                "file": (
                    "large.pdf",
                    b"x" * (DEFAULT_MAX_PDF_BYTES + 1),
                    "application/pdf",
                )
            }
        )
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "pdf_too_large",
            "message": "The PDF exceeds the allowed file size.",
        }
    }


def test_parse_endpoint_allows_the_configured_local_frontend_origin() -> None:
    response = asyncio.run(cors_preflight())

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-methods"] == "POST"


def test_development_ui_and_static_assets_are_served() -> None:
    root = asyncio.run(request("GET", "/"))
    script = asyncio.run(request("GET", "/static/app.js"))
    styles = asyncio.run(request("GET", "/static/styles.css"))

    assert root.status_code == script.status_code == styles.status_code == 200
    assert 'id="source-code-link"' in root.text
    assert 'id="session-persistence-notice"' in root.text
    assert "/license" in root.text and "/third-party-notices" in root.text
    assert 'fetch("/api/v1/about")' in script.text
    assert "İlana Özel CV" in root.text
    assert "/api/v1/cv/analyze" in script.text


def test_static_ui_javascript_is_syntax_valid_and_matches_the_html_contract() -> None:
    root = asyncio.run(request("GET", "/")).text
    script = asyncio.run(request("GET", "/static/app.js")).text
    for identifier in ("pdf", "analyze-cv", "general-coach", "job-text", "analyze-job", "job-coach", "generation-area", "generation-mode", "generate-review", "generation-review"):
        assert f'id="{identifier}"' in root
    for endpoint in ("/api/v1/cv/analyze", "/api/v1/cv/coach-answer", "/api/v1/cv/coach-candidate/resolve", "/api/v1/jobs/analyze", "/api/v1/cv/generate/review"):
        assert endpoint in script
    # Each user action has one canonical static-UI request path.  Legacy
    # handlers must not remain alongside the active job/coach bindings.
    assert script.count('el("analyze-job").onclick') == 1
    assert script.count('"/api/v1/cv/coach-answer"') == 1
    assert "Cover Letter İndir" not in root
    assert "Seçilen dosya:" in script
    assert "sessionStorage" in script
    assert "localStorage" not in script
    assert '"/api/v1/cv/session/recover"' in script
    assert '"/api/v1/cv/session/delete"' in script
    assert 'renderSessionPersistenceNotice(info.session_persistence_mode)' in script
    assert "Bu analiz geçicidir." in script
    assert "Oturumu ve Verilerimi Sil" in root
    assert "İlana Özel CV için önce iş ilanı metnini analiz edin." in script
    assert "potential_impact" in script
    for profile_field in ("work_experiences", "education", "skills", "tools", "projects", "publications"):
        assert profile_field in script
    node = shutil.which("node")
    if node is not None:
        asset = Path(__file__).parents[1] / "app" / "static" / "app.js"
        completed = subprocess.run([node, "--check", str(asset)], capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stderr


def test_generation_review_ui_uses_only_the_public_review_contract() -> None:
    root = asyncio.run(request("GET", "/")).text
    script = asyncio.run(request("GET", "/static/app.js")).text

    assert "Genel CV" in root and "İlana Özel CV" in root
    assert "CV Taslağını Oluştur" in root
    assert 'JSON.stringify({ session_id: sessionId, mode })' in script
    assert "renderGenerationReview" in script
    assert "hasExportableContent" in script
    assert 'el("download-docx").disabled = !hasExportableContent' in script
    assert 'el("download-pdf").disabled = !hasExportableContent' in script
    assert "atomic_evidence_id" not in script
    assert "rendered_claim_id" not in script


def test_cv_analysis_answer_and_job_analysis_flow_is_session_scoped() -> None:
    analysis = asyncio.run(
        request(
            "POST",
            "/api/v1/cv/analyze",
            files={"file": ("candidate.pdf", text_pdf("SKILLS", "- SAP"), "application/pdf")},
        )
    )
    assert analysis.status_code == 200
    result = analysis.json()
    assert result["session_id"]
    assert "profile" in result and "quality" in result and "coach" in result

    question = next(item for item in result["coach"]["questions"] if item["category"] == "certification")
    answer = asyncio.run(request("POST", "/api/v1/cv/coach-answer", json={
        "session_id": result["session_id"], "question_id": question["question_id"], "answer_text": "PMP",
    }))
    assert answer.status_code == 200
    assert answer.json()["status"] == "candidate_created"
    assert answer.json()["candidate"]["verification_status"] == "inferred_unverified"

    job = asyncio.run(request("POST", "/api/v1/jobs/analyze", json={
        "session_id": result["session_id"],
        "job_text": "Job Title: Engineer\nSkills\n- SAP",
    }))
    assert job.status_code == 200
    job_result = job.json()
    assert job_result["job_analysis"]["profile"]["title"] == "Engineer"
    assert job_result["job_score"]["match_score"] == 100
    assert "job_match" in job_result and "job_coach" in job_result


def test_public_api_contract_scrubs_provenance_and_documents_critical_responses() -> None:
    analysis = asyncio.run(request(
        "POST",
        "/api/v1/cv/analyze",
        files={"file": ("candidate.pdf", text_pdf("candidate@example.com", "SKILLS", "- SAP"), "application/pdf")},
    ))

    assert analysis.status_code == 200
    payload = analysis.json()
    serialized = analysis.text
    skill = payload["profile"]["skills"][0]
    assert skill["statement"] == "SAP"
    assert skill["verification_status"] == "verified"
    for internal_field in ("source", "identity", "evidence_references", "matched_evidence_references", "source_reference"):
        assert f'"{internal_field}"' not in serialized

    invalid = asyncio.run(request("POST", "/api/v1/jobs/analyze", json={}))
    assert invalid.status_code == 422
    assert invalid.json() == {"error": {"code": "invalid_request", "message": "The request data is invalid."}}
    assert "loc" not in invalid.text and "input" not in invalid.text

    schema = app.openapi()["paths"]
    assert schema["/api/v1/cv/analyze"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("CVAnalysisResponse")
    assert schema["/api/v1/cv/generate/review"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("ReviewedCvDraft")
    assert schema["/api/v1/jobs/analyze"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("JobAnalysisResponse")


def test_pdf_parser_to_analysis_endpoint_retains_structured_record_evidence() -> None:
    response = asyncio.run(request("POST", "/api/v1/cv/analyze", files={
        "file": (
            "chronological.pdf",
            text_pdf(
                "WORK EXPERIENCE", "May 2024 -", "Installation Engineer, Example Systems",
                "- Improved commissioning output by 80% using SAP", "EDUCATION",
                "Sep 2017 - Oct 2022", "Mechanical Engineering", "Example Technical University",
                "SKILLS", "- Tool A", "- Tool B",
            ),
            "application/pdf",
        )
    }))

    assert response.status_code == 200
    result = response.json()
    assert len(result["profile"]["work_experiences"]) == 1
    assert len(result["profile"]["education"]) == 1
    assert [item["statement"] for item in result["profile"]["skills"]] == ["Tool A", "Tool B"]
    assert any(fact["metrics"] for fact in result["profile"]["work_experiences"][0]["facts"])
    assert "structured_experience_present" in {item["code"] for item in result["quality"]["findings"]}


def test_upload_analysis_serialization_quality_and_coach_use_the_same_structured_profile() -> None:
    lines = [
        "WORK EXPERIENCE",
        "May 2024 -", "Installation Engineer, Example Systems", "- Planned commissioning using SAP",
        "Oct 2022 - Apr 2024", "Production Engineer, Example Materials", "- Improved output by 80% using OEE", "Project: Efficiency improvement",
        "Feb 2022 - Oct 2022", "Production Engineer Intern, Example Materials", "- Supported production analysis",
        "Nov 2020 - Feb 2022", "Mechanical Engineer Intern, Example Engineering", "- Produced drawings with REVIT",
        "Sep 2020 - Oct 2020", "Engineering Intern, Example Machinery", "- Completed quality-control training",
        "EDUCATION", "Sep 2017 - Oct 2022", "Mechanical Engineering", "Example Technical University",
        "SKILLS", "- Tool A", "- Tool B", "- Tool C", "- Tool D", "- Tool E", "- Tool F", "- Tool G", "- Tool H", "- Tool I",
        "ACCOMPLISHMENTS", "Article: Manufacturing process study", "Sport activities",
    ]
    response = asyncio.run(request("POST", "/api/v1/cv/analyze", files={
        "file": ("multi-page-shape.pdf", text_pdf(*lines), "application/pdf")
    }))

    assert response.status_code == 200
    result = response.json()
    profile, quality, coach = result["profile"], result["quality"], result["coach"]
    assert len(profile["work_experiences"]) == 5
    assert len(profile["education"]) == 1
    assert len(profile["skills"]) == 9
    assert [item["name"] for item in profile["projects"]] == ["Efficiency improvement"]
    assert [item["title"] for item in profile["publications"]] == ["Manufacturing process study"]
    finding_codes = {item["code"] for item in quality["findings"]}
    assert {"structured_experience_present", "structured_education_present", "trusted_skills_present", "explicit_metrics"} <= finding_codes
    assert not any(question["category"] == "metric" and question["related_role"] == "Production Engineer" for question in coach["questions"])


def test_job_and_answer_routes_return_safe_session_errors() -> None:
    answer = asyncio.run(request("POST", "/api/v1/cv/coach-answer", json={
        "session_id": "missing", "question_id": "missing", "answer_text": "PMP",
    }))
    job = asyncio.run(request("POST", "/api/v1/jobs/analyze", json={"session_id": "missing", "job_text": "Requirements\n- SAP"}))

    assert answer.status_code == job.status_code == 404
    assert answer.json()["error"]["code"] == job.json()["error"]["code"] == "analysis_session_not_found"


def test_session_delete_is_idempotent_and_isolated_from_other_sessions() -> None:
    first = asyncio.run(request("POST", "/api/v1/cv/analyze", files={
        "file": ("first.pdf", text_pdf("SKILLS", "- SAP"), "application/pdf"),
    })).json()
    second = asyncio.run(request("POST", "/api/v1/cv/analyze", files={
        "file": ("second.pdf", text_pdf("SKILLS", "- Python"), "application/pdf"),
    })).json()

    question = next(item for item in first["coach"]["questions"] if item["category"] == "certification")
    candidate = asyncio.run(request("POST", "/api/v1/cv/coach-answer", json={
        "session_id": first["session_id"], "question_id": question["question_id"], "answer_text": "PMP",
    })).json()
    accepted = asyncio.run(request("POST", "/api/v1/cv/coach-candidate/resolve", json={
        "session_id": first["session_id"], "candidate_id": candidate["candidate_id"], "action": "accept",
    }))
    job = asyncio.run(request("POST", "/api/v1/jobs/analyze", json={
        "session_id": first["session_id"], "job_text": "Data Analyst\n- SAP",
    }))
    before_delete = session_store.get(first["session_id"])

    assert accepted.status_code == job.status_code == 200
    assert before_delete is not None
    assert before_delete.resolved_candidate_ids
    assert any(fact.statement == "PMP" for fact in before_delete.profile.additional_facts)
    assert before_delete.job_analysis is not None
    persistence = SQLiteSessionPersistence(get_settings().session_db_path, ttl_hours=24)
    snapshot = persistence.load(first["session_id"])
    assert snapshot is not None
    assert snapshot.quality is not None
    assert not {"document", "pdf", "geometry"} & set(snapshot.model_dump())

    deleted = asyncio.run(request("POST", "/api/v1/cv/session/delete", json={"session_id": first["session_id"]}))
    repeated = asyncio.run(request("POST", "/api/v1/cv/session/delete", json={"session_id": first["session_id"]}))
    missing = asyncio.run(request("POST", "/api/v1/cv/session/recover", json={"session_id": first["session_id"]}))
    available = asyncio.run(request("POST", "/api/v1/cv/session/recover", json={"session_id": second["session_id"]}))

    assert deleted.json() == repeated.json() == {"status": "deleted"}
    assert session_store.get(first["session_id"]) is None
    assert persistence.load(first["session_id"]) is None
    assert AnalysisSessionStore(persistence=SQLiteSessionPersistence(get_settings().session_db_path, ttl_hours=24)).get(first["session_id"]) is None
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "analysis_session_not_found"
    assert available.status_code == 200
    assert available.json()["profile"]["skills"][0]["statement"] == "Python"

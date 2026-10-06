import asyncio
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import httpx
import pymupdf
import pytest

from app.main import app
from app.api.routes.cv import session_store
from app.services.cover_letter.rewrite.service import enhance_cover_letter_wording
from app.services.controlled_rewrite import RewriteProposal, RewriteFinalStatus
from tests.golden.data import SCENARIOS, GoldenScenario


def _pdf(scenario: GoldenScenario) -> bytes:
    document = pymupdf.open(); page = document.new_page()
    lines = (scenario.candidate_name, scenario.candidate_title, scenario.education, "candidate@example.com", "SKILLS", *(f"- {skill}" for skill in scenario.skills))
    for index, line in enumerate(lines): page.insert_text((72, 72 + index * 20), line)
    data = document.tobytes(); document.close(); return data


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://golden") as client:
        return await client.request(method, path, **kwargs)


def _analyze(scenario: GoldenScenario) -> str:
    response = asyncio.run(_request("POST", "/api/v1/cv/analyze", files={"file": (f"{scenario.key}.pdf", _pdf(scenario), "application/pdf")}))
    assert response.status_code == 200, response.text
    profile = response.json()["profile"]
    assert set(scenario.skills) <= {item["statement"] for item in profile["skills"]}
    return response.json()["session_id"]


def _job(session_id: str, scenario: GoldenScenario) -> httpx.Response:
    text = f"Job Title: {scenario.job_title}\nCompany: {scenario.company}\nSkills\n" + "\n".join(f"- {value}" for value in scenario.job_requirements)
    return asyncio.run(_request("POST", "/api/v1/jobs/analyze", json={"session_id": session_id, "job_text": text}))


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.key)
def test_golden_targeted_pipeline_never_promotes_job_only_keywords(scenario: GoldenScenario) -> None:
    session_id = _analyze(scenario)
    assert _job(session_id, scenario).status_code == 200
    review = asyncio.run(_request("POST", "/api/v1/cv/generate/review", json={"session_id": session_id, "mode": "targeted"}))
    assert review.status_code == 200
    content = " ".join(item["text"] for item in review.json()["review"]["skills"])
    for forbidden in scenario.forbidden:
        assert forbidden.casefold() not in content.casefold()
    cover = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"}))
    assert cover.status_code == 200
    letter = cover.json()
    assert letter["target_role"] == scenario.job_title and letter["target_company"] == scenario.company
    body = " ".join(letter["body_sections"])
    for forbidden in scenario.forbidden:
        assert forbidden.casefold() not in body.casefold()
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/quality", json={"session_id": session_id, "draft_id": review.json()["draft_id"]})).status_code == 200
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/validate", json={"session_id": session_id, "draft_id": review.json()["draft_id"]})).status_code == 200


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: f"{item.key}-safe-rewrite")
def test_golden_safe_rewrite_preserves_each_candidate_claim(scenario: GoldenScenario) -> None:
    class SafeProvider:
        def rewrite_claim(self, *, source_text: str, mode: str) -> RewriteProposal:
            return RewriteProposal(rewritten_text=source_text)
    result = enhance_cover_letter_wording(item_id=scenario.key, original_text=scenario.skills[0], category="SKILL", provider=SafeProvider())
    assert result.final_status is RewriteFinalStatus.ACCEPTED
    assert result.rewritten_text == scenario.skills[0]


@pytest.mark.parametrize("scenario", SCENARIOS[:2], ids=lambda item: f"{item.key}-general")
def test_golden_general_generation_requires_no_job_and_cover_letter_remains_targeted_only(scenario: GoldenScenario) -> None:
    session_id = _analyze(scenario)
    general = asyncio.run(_request("POST", "/api/v1/cv/generate/review", json={"session_id": session_id, "mode": "general"}))
    assert general.status_code == 200
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"})).status_code == 409


def test_golden_mechanical_full_review_export_and_job_state_isolation() -> None:
    scenario = SCENARIOS[0]; session_id = _analyze(scenario)
    assert _job(session_id, scenario).status_code == 200
    profile_before = deepcopy(session_store.get(session_id).profile.model_dump(mode="json"))
    cv = asyncio.run(_request("POST", "/api/v1/cv/generate/review", json={"session_id": session_id, "mode": "targeted"})).json()
    letter = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"})).json()
    item_id = letter["items"][0]["item_id"]
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/decision", json={"session_id": session_id, "draft_id": letter["draft_id"], "item_id": item_id, "decision": "remove"})).status_code == 200
    removed = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/export/pdf", json={"session_id": session_id, "draft_id": letter["draft_id"]}))
    removed_text = "\n".join(page.get_text() for page in pymupdf.open(stream=removed.content, filetype="pdf"))
    assert letter["items"][0]["text"] not in removed_text
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter/decision", json={"session_id": session_id, "draft_id": letter["draft_id"], "item_id": item_id, "decision": "keep"})).status_code == 200
    for endpoint in ("/api/v1/cv/generate/export/docx", "/api/v1/cv/generate/export/pdf", "/api/v1/cv/generate/cover-letter/export/docx", "/api/v1/cv/generate/cover-letter/export/pdf"):
        draft_id = cv["draft_id"] if "cover-letter" not in endpoint else letter["draft_id"]
        exported = asyncio.run(_request("POST", endpoint, json={"session_id": session_id, "draft_id": draft_id}))
        assert exported.status_code == 200
        if endpoint.endswith("docx"):
            with ZipFile(BytesIO(exported.content)) as archive: assert "word/document.xml" in archive.namelist()
        else:
            assert pymupdf.open(stream=exported.content, filetype="pdf").page_count >= 1
    variation = GoldenScenario("mechanical-automation", scenario.candidate_name, scenario.candidate_title, scenario.education, scenario.skills, "Automation Engineer", "Automation Labs", ("Siemens PLC", "SAP ERP", "Python"), ("Siemens", "SAP", "Python"))
    assert _job(session_id, variation).status_code == 200
    later = asyncio.run(_request("POST", "/api/v1/cv/generate/cover-letter", json={"session_id": session_id, "mode": "targeted"})).json()
    assert later["target_company"] == "Automation Labs" and "Apex Industrial Systems" not in later["opening"]
    assert session_store.get(session_id).profile.model_dump(mode="json") == profile_before


class _UnsafeProvider:
    def rewrite_claim(self, *, source_text: str, mode: str) -> RewriteProposal:
        return RewriteProposal(rewritten_text="Worked extensively with Siemens PLC systems and Python.")


def test_golden_rewrite_blocks_job_keyword_injection() -> None:
    result = enhance_cover_letter_wording(item_id="golden", original_text="Worked with PLC systems.", category="SKILL", provider=_UnsafeProvider())
    assert result.final_status is RewriteFinalStatus.REJECTED
    assert result.rewritten_text == "Worked with PLC systems."

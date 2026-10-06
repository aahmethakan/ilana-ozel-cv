"""ASGI coverage for unverified company-continuation analysis state."""

import asyncio

import httpx
import pymupdf
import pytest

from app.api.routes.cv import session_store
from app.main import app


def _pdf(rows: tuple[tuple[float, float, str], ...]) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for x, y, text in rows:
        page.insert_text((x, y), text, fontsize=10)
    data = document.tobytes()
    document.close()
    return data


def _analyze(content: bytes) -> str:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/cv/analyze",
                files={"file": ("continuation.pdf", content, "application/pdf")},
            )

    response = asyncio.run(request())
    assert response.status_code == 200
    return response.json()["session_id"]


def _post(path: str, payload: dict) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=payload)
    return asyncio.run(request())


def _review_continuation_id(session_id: str) -> str:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/cv/career-profile-review", json={"session_id": session_id})
    response = asyncio.run(request())
    assert response.status_code == 200
    return next(item["item_id"] for item in response.json()["items"] if item["category"] == "WORK_EXPERIENCE_COMPANY")


def _review_items(session_id: str) -> list[dict]:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/cv/career-profile-review", json={"session_id": session_id})
    response = asyncio.run(request())
    assert response.status_code == 200
    return response.json()["items"]


def _company_omitted_roles_pdf() -> bytes:
    return _pdf((
        (72, 72, "WORK EXPERIENCE"),
        (72, 96, "Planner"),
        (72, 120, "Example Logistics"),
        (72, 144, "2019 - 2021"),
        (72, 168, "- Role one evidence"),
        (72, 192, "Senior Planner"),
        (72, 216, "2021 - 2023"),
        (72, 240, "- Role two evidence"),
        (72, 264, "Lead Planner"),
        (72, 288, "2023 - Present"),
        (72, 312, "- Role three evidence"),
    ))


def test_analyze_persists_two_exact_unverified_continuation_pairs() -> None:
    session_id = _analyze(_company_omitted_roles_pdf())
    session = session_store.get(session_id)

    assert session is not None
    assert [(role.company, role.title) for role in session.profile.work_experiences] == [("Example Logistics", "Planner")]
    states = tuple(session.continuation_candidates.values())
    assert len(states) == 2
    assert {state.work_candidate.title.value for state in states if state.work_candidate.title} == {"Senior Planner", "Lead Planner"}
    assert all(state.work_candidate.company is None for state in states)
    assert all(state.evidence.proposed_company == "Example Logistics" for state in states)
    assert all(state.evidence.verification_status == "inferred_unverified" for state in states)
    assert len({state.work_candidate.candidate_id for state in states}) == 2
    assert len({state.evidence.candidate_id for state in states}) == 2
    for state in states:
        assert state.work_candidate.title is not None
        assert state.work_candidate.title.value_source.reference in state.evidence.current_role_references
        assert state.evidence.previous_company_reference not in state.evidence.current_role_references
    by_title = {state.work_candidate.title.value: state for state in states if state.work_candidate.title}
    assert {source.original_text for source in by_title["Senior Planner"].work_candidate.origin.evidence_sources} == {
        "Senior Planner", "- Role two evidence",
    }
    assert {source.original_text for source in by_title["Lead Planner"].work_candidate.origin.evidence_sources} == {
        "Lead Planner", "- Role three evidence",
    }


def test_analyze_does_not_create_continuation_for_an_explicit_company_role() -> None:
    session_id = _analyze(_pdf((
        (72, 72, "WORK EXPERIENCE"),
        (72, 96, "Planner"), (72, 120, "Example Logistics"), (72, 144, "2019 - 2021"),
        (72, 168, "- Role one evidence"),
        (72, 192, "Senior Planner"), (72, 216, "Other Logistics"), (72, 240, "2021 - Present"),
        (72, 264, "- Role two evidence"),
    )))
    session = session_store.get(session_id)

    assert session is not None
    assert [(role.company, role.title) for role in session.profile.work_experiences] == [
        ("Example Logistics", "Planner"),
        ("Other Logistics", "Senior Planner"),
    ]
    assert session.continuation_candidates == {}


def test_analyze_fails_closed_when_no_explicit_previous_company_exists() -> None:
    session_id = _analyze(_pdf((
        (72, 72, "WORK EXPERIENCE"),
        (72, 96, "Senior Planner"), (72, 120, "2021 - Present"),
        (72, 144, "- Role evidence"),
    )))
    session = session_store.get(session_id)

    assert session is not None
    assert session.profile.work_experiences == ()
    assert len(session.continuation_candidates) == 0


def test_analyze_fails_closed_for_company_evidence_in_another_pdf_column() -> None:
    session_id = _analyze(_pdf((
        (72, 72, "WORK EXPERIENCE"),
        (72, 96, "Senior Planner"), (72, 120, "2021 - Present"),
        (72, 144, "- Left-column role evidence"),
        (330, 96, "Planner"), (330, 120, "Example Logistics"), (330, 144, "2019 - 2021"),
        (330, 168, "- Right-column role evidence"),
    )))
    session = session_store.get(session_id)

    assert session is not None
    assert len(session.continuation_candidates) == 0


def test_analyze_is_deterministic_without_carrying_old_continuation_state() -> None:
    first_id = _analyze(_company_omitted_roles_pdf())
    second_id = _analyze(_company_omitted_roles_pdf())
    first = session_store.get(first_id)
    second = session_store.get(second_id)

    assert first is not None and second is not None and first_id != second_id
    assert tuple(first.continuation_candidates) == tuple(second.continuation_candidates)
    assert first.coach_candidates == second.coach_candidates == {}


def test_continuation_store_rejects_duplicate_evidence_ids() -> None:
    session_id = _analyze(_company_omitted_roles_pdf())
    session = session_store.get(session_id)

    assert session is not None
    state = next(iter(session.continuation_candidates.values()))
    with pytest.raises(ValueError, match="must be unique"):
        session_store.set_continuation_candidates(session_id, candidates=(state, state))


def test_accept_resolves_only_the_server_owned_company_proposal() -> None:
    session_id = _analyze(_company_omitted_roles_pdf())
    session = session_store.get(session_id)
    assert session is not None
    candidate_id = _review_continuation_id(session_id)

    response = _post("/api/v1/cv/continuation-candidate/resolve", {
        "session_id": session_id, "candidate_id": candidate_id, "action": "ACCEPT",
    })

    assert response.status_code == 200
    assert set(response.json()) == {"status", "candidate_id", "message"}
    assert response.json()["status"] == "resolved"
    resolved = next(iter(session.continuation_resolutions.values())).resolved_record
    assert resolved is not None and resolved.company is not None
    assert resolved.company.value == "Example Logistics"
    assert resolved.company.verification_status.value == "user_provided"
    assert ("Example Logistics", "Planner") in [(role.company, role.title) for role in session.profile.work_experiences]
    assert len(session.profile.work_experiences) == 2
    assert session.job_match is None and session.current_generated_draft is None
    assert _post("/api/v1/cv/continuation-candidate/resolve", {
        "session_id": session_id, "candidate_id": candidate_id, "action": "ACCEPT",
    }).status_code == 409


def test_public_continuation_projection_hides_internal_lineage_and_leave_stays_unresolved() -> None:
    async def analyze_response() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/cv/analyze", files={"file": ("continuation.pdf", _company_omitted_roles_pdf(), "application/pdf")})

    analysis = asyncio.run(analyze_response())
    assert analysis.status_code == 200
    public = analysis.json()["career_profile_review"]["items"][0]
    assert set(public) == {"item_id", "category", "title", "question", "proposed_value", "reason", "potential_impact", "status", "actions"}
    assert "reference" not in str(public).casefold() and "geometry" not in str(public).casefold()
    response = _post("/api/v1/cv/continuation-candidate/resolve", {
        "session_id": analysis.json()["session_id"], "candidate_id": public["item_id"], "action": "LEAVE_UNRESOLVED",
    })
    assert response.status_code == 200 and response.json()["status"] == "partially_resolved"
    session = session_store.get(analysis.json()["session_id"])
    assert session is not None and all(role.title != "Senior Planner" for role in session.profile.work_experiences)


def test_accept_rebuilds_a_generation_context_with_the_resolved_work_record() -> None:
    session_id = _analyze(_company_omitted_roles_pdf())
    session = session_store.get(session_id)
    assert session is not None
    candidate_id = _review_continuation_id(session_id)
    assert _post("/api/v1/cv/continuation-candidate/resolve", {
        "session_id": session_id, "candidate_id": candidate_id, "action": "ACCEPT",
    }).status_code == 200
    context = session_store.get_unified_career_context(session_id)
    assert context is not None
    entries = context.structured_assembly.profile.work_experiences
    assert len(entries) == 1
    assert entries[0].record.company is not None
    assert entries[0].record.company.verification_status.value == "user_provided"


def test_correct_reject_leave_and_payload_injection_are_fail_closed() -> None:
    session_id = _analyze(_company_omitted_roles_pdf())
    session = session_store.get(session_id)
    assert session is not None
    candidate_ids = tuple(item["item_id"] for item in _review_items(session_id))

    rejected = _post("/api/v1/cv/continuation-candidate/resolve", {
        "session_id": session_id, "candidate_id": candidate_ids[0], "action": "REJECT",
    })
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert all(role.title != "Senior Planner" for role in session.profile.work_experiences)
    corrected = _post("/api/v1/cv/continuation-candidate/resolve", {
        "session_id": session_id, "candidate_id": candidate_ids[1], "action": "CORRECT", "correction": "Corrected Company",
    })
    assert corrected.status_code == 200 and corrected.json()["status"] == "resolved"
    assert any(role.company == "Corrected Company" for role in session.profile.work_experiences)
    injected = _post("/api/v1/cv/continuation-candidate/resolve", {
        "session_id": session_id, "candidate_id": candidate_ids[1], "action": "ACCEPT", "company": "Injected Company",
    })
    assert injected.status_code == 422


@pytest.mark.parametrize("payload", [
    {"action": "CORRECT", "correction": " "},
    {"action": "ACCEPT", "correction": "no"},
    {"action": "REJECT", "correction": "no"},
    {"action": "LEAVE_UNRESOLVED", "correction": "no"},
])
def test_invalid_continuation_resolution_payloads_are_rejected(payload: dict) -> None:
    session_id = _analyze(_company_omitted_roles_pdf())
    session = session_store.get(session_id)
    assert session is not None
    response = _post("/api/v1/cv/continuation-candidate/resolve", {
        "session_id": session_id, "candidate_id": next(iter(session.continuation_candidates)), **payload,
    })
    assert response.status_code == 422

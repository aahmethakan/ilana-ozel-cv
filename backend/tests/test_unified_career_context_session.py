import asyncio
import threading

import httpx
import pymupdf

from app.api.routes.cv import session_store
from app.domain.career import CareerFact, CareerProfile, ContactInfo, ContactValue, FactSource, SourceType, VerificationStatus
from app.extraction.career import UnresolvedEvidence
from app.main import app
from app.parsers.pdf import parse_pdf
from app.services.career_context import build_analyzed_unified_career_context
from app.services.analysis_session import AnalysisSession, AnalysisSessionStore
from app.services.analysis_session.persistence import PersistedAnalysisSessionV1, SQLiteSessionPersistence
from app.core.config import get_settings
from app.services.career_gap_analysis import analyze_career_profile_gaps
from app.services.cv_quality_analysis import CVQualityDimension, analyze_cv_quality
from app.services.profile_readiness import assess_unified_career_readiness


def _pdf(*lines: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + (index * 24)), line)
    data = document.tobytes()
    document.close()
    return data


async def _request(method: str, path: str, **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def _profile() -> CareerProfile:
    source = FactSource(source_type=SourceType.MASTER_CV, reference="block:skills", original_text="SAP")
    return CareerProfile(skills=(CareerFact(statement="SAP", skills=("SAP",), verification_status=VerificationStatus.VERIFIED, source=source),))


def _ready_profile() -> CareerProfile:
    source = FactSource(source_type=SourceType.MASTER_CV, reference="block:contact", original_text="candidate@example.com")
    return _profile().model_copy(update={"contact": ContactInfo(email=ContactValue(value="candidate@example.com", source=source))})


def test_analyzed_context_is_immutable_aggregate_and_preserves_unresolved_evidence() -> None:
    unresolved = (UnresolvedEvidence(block_reference="block:experience", reason="ambiguous_experience_content"),)
    profile = _profile()

    context = build_analyzed_unified_career_context(profile=profile, unresolved_evidence=unresolved)

    assert context.atomic_profile == profile
    assert context.structured_assembly.profile.work_experiences == ()
    assert context.evidence_convergence.unbound_unresolved_evidence == unresolved
    assert context.evidence_coverage.unbound_unresolved_evidence == unresolved
    assert assess_unified_career_readiness(context).unresolved_count >= 1
    assert profile == _profile()


def test_cv_analysis_stores_server_built_context_without_expanding_response_contract() -> None:
    response = asyncio.run(_request(
        "POST",
        "/api/v1/cv/analyze",
        files={"file": ("candidate.pdf", _pdf("SKILLS", "- SAP"), "application/pdf")},
        data={"unified_career_context": '{"atomic_profile":{"skills":["injected"]}}'},
    ))

    assert response.status_code == 200
    payload = response.json()
    assert "unified_career_context" not in payload
    context = session_store.get_unified_career_context(payload["session_id"])
    assert context is not None
    assert [fact.statement for fact in context.atomic_profile.skills] == ["SAP"]
    assert context.evidence_convergence == context.evidence_convergence.model_copy(deep=True)


def test_new_analysis_sessions_hold_their_own_latest_context_and_failed_upload_changes_none() -> None:
    first = asyncio.run(_request(
        "POST", "/api/v1/cv/analyze",
        files={"file": ("first.pdf", _pdf("candidate@example.com", "SKILLS", "- SAP"), "application/pdf")},
    )).json()
    second = asyncio.run(_request(
        "POST", "/api/v1/cv/analyze",
        files={"file": ("second.pdf", _pdf("SKILLS", "- Python"), "application/pdf")},
    )).json()

    assert [fact.statement for fact in session_store.get_unified_career_context(first["session_id"]).atomic_profile.skills] == ["SAP"]  # type: ignore[union-attr]
    assert [fact.statement for fact in session_store.get_unified_career_context(second["session_id"]).atomic_profile.skills] == ["Python"]  # type: ignore[union-attr]
    failed = asyncio.run(_request("POST", "/api/v1/cv/analyze", files={"file": ("bad.pdf", b"not a pdf", "application/pdf")}))
    assert failed.status_code == 422
    assert session_store.get_unified_career_context(second["session_id"]) is not None


def test_session_store_replaces_only_the_current_authoritative_context() -> None:
    profile = _profile()
    store = AnalysisSessionStore()
    session_id = store.create(AnalysisSession(
        profile=profile,
        quality=analyze_cv_quality(profile),
        coach=analyze_career_profile_gaps(profile),
        questions={},
    ))
    first = build_analyzed_unified_career_context(profile=profile)
    second = build_analyzed_unified_career_context(
        profile=profile,
        unresolved_evidence=(UnresolvedEvidence(block_reference="block:new", reason="ambiguous_skill_content"),),
    )

    assert store.get_unified_career_context(session_id) is None
    store.set_unified_career_context(session_id, context=first)
    store.set_unified_career_context(session_id, context=second)

    assert store.get_unified_career_context(session_id) == second
    assert store.get_unified_career_context(session_id) != first


def test_persisted_canonical_session_rehydrates_without_generated_state() -> None:
    persistence = SQLiteSessionPersistence(get_settings().session_db_path, ttl_hours=24)
    document = parse_pdf(_pdf("PERSONAL INFORMATION", "candidate@example.com", "SKILLS", "- SAP"), "candidate.pdf")
    profile = _profile()
    quality = analyze_cv_quality(profile, document=document)
    assert quality != analyze_cv_quality(profile, document=None)
    context = build_analyzed_unified_career_context(profile=profile)
    store = AnalysisSessionStore(persistence=persistence)
    session_id = store.create(AnalysisSession(profile=profile, quality=quality, coach=analyze_career_profile_gaps(profile), questions={}, unified_career_context=context))
    restored = AnalysisSessionStore(persistence=SQLiteSessionPersistence(get_settings().session_db_path, ttl_hours=24)).get(session_id)

    assert restored is not None
    assert restored.profile == profile
    assert restored.quality == quality
    scores = {item.dimension: item.score for item in quality.dimensions}
    restored_scores = {item.dimension: item.score for item in restored.quality.dimensions}
    assert restored_scores[CVQualityDimension.STRUCTURE] == scores[CVQualityDimension.STRUCTURE]
    assert restored_scores[CVQualityDimension.ATS_READINESS] == scores[CVQualityDimension.ATS_READINESS]
    assert restored.unified_career_context is not None
    assert restored.current_generated_draft is None
    assert restored.current_cover_letter is None
    legacy_snapshot = PersistedAnalysisSessionV1.model_validate({
        "context_revision": 0,
        "profile": profile.model_dump(mode="json"),
    })
    assert legacy_snapshot.quality is None
    assert store._restore(legacy_snapshot).quality == analyze_cv_quality(profile, document=None)
    persistence.delete(session_id)


def test_readiness_rejection_is_opaque_session_scoped_and_unblocks_only_after_context_rebuild() -> None:
    unresolved = (UnresolvedEvidence(block_reference="page:1:block:ambiguous", section_type=None, reason="ambiguous_source_content"),)
    profile = _ready_profile()
    context = build_analyzed_unified_career_context(profile=profile, unresolved_evidence=unresolved)
    session_id = session_store.create(AnalysisSession(
        profile=profile, quality=analyze_cv_quality(profile, unresolved_evidence=unresolved),
        coach=analyze_career_profile_gaps(profile), questions={}, unified_career_context=context,
        unresolved_evidence=unresolved,
    ))
    other_id = session_store.create(AnalysisSession(
        profile=_ready_profile(), quality=analyze_cv_quality(_ready_profile()),
        coach=analyze_career_profile_gaps(_ready_profile()), questions={},
        unified_career_context=build_analyzed_unified_career_context(profile=_ready_profile()),
    ))
    review = asyncio.run(_request("POST", "/api/v1/cv/career-profile-review", json={"session_id": session_id}))
    assert review.status_code == 200
    readiness = review.json()["readiness"]
    assert readiness["status"] == "needs_review"
    item = readiness["items"][0]
    assert item["actions"] == ["REJECT"]
    assert item["finding_id"].startswith("readiness:")
    assert "page:" not in str(item) and "ambiguous_source_content" not in str(item)

    blocked = asyncio.run(_request("POST", "/api/v1/cv/generate/review", json={"session_id": session_id, "mode": "general"}))
    invalid = asyncio.run(_request("POST", "/api/v1/cv/readiness/resolve", json={"session_id": session_id, "finding_id": item["finding_id"], "action": "confirm"}))
    cross_session = asyncio.run(_request("POST", "/api/v1/cv/readiness/resolve", json={"session_id": other_id, "finding_id": item["finding_id"], "action": "reject"}))
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "generation_readiness_needs_review"
    assert invalid.status_code == 422
    assert cross_session.status_code == 404

    resolved = asyncio.run(_request("POST", "/api/v1/cv/readiness/resolve", json={"session_id": session_id, "finding_id": item["finding_id"], "action": "reject"}))
    assert resolved.status_code == 200
    assert resolved.json()["career_profile_review"]["readiness"]["status"] == "ready"
    current = session_store.get(session_id)
    assert current is not None
    assert current.profile == profile
    assert len(current.unresolved_evidence) == 1
    assert current.readiness_rejected_evidence_ids == {item["finding_id"]}
    restored = AnalysisSessionStore(persistence=SQLiteSessionPersistence(get_settings().session_db_path, ttl_hours=24)).get(session_id)
    assert restored is not None and restored.readiness_rejected_evidence_ids == {item["finding_id"]}
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/review", json={"session_id": session_id, "mode": "general"})).status_code == 200
    job = asyncio.run(_request("POST", "/api/v1/jobs/analyze", json={"session_id": session_id, "job_text": "Job Title: Analyst\nSkills\n- SAP"}))
    assert job.status_code == 200
    assert asyncio.run(_request("POST", "/api/v1/cv/generate/review", json={"session_id": session_id, "mode": "targeted"})).status_code == 200
    session_store.delete(session_id)
    session_store.delete(other_id)


def test_same_process_live_session_mutations_do_not_overwrite_or_resurrect_deleted_state() -> None:
    persistence = SQLiteSessionPersistence(get_settings().session_db_path, ttl_hours=24)
    store = AnalysisSessionStore(persistence=persistence)
    session_id = store.create(AnalysisSession(profile=_profile(), quality=analyze_cv_quality(_profile()), coach=analyze_career_profile_gaps(_profile()), questions={}))
    a_read = threading.Event(); b_committed = threading.Event()

    def first() -> None:
        session = store.get(session_id); assert session is not None
        a_read.set(); assert b_committed.wait(timeout=2)
        session.coach_resolution_status["a"] = "accepted"
        store.persist_session(session_id)

    def second() -> None:
        assert a_read.wait(timeout=2)
        session = store.get(session_id); assert session is not None
        session.coach_resolution_status["b"] = "accepted"
        store.persist_session(session_id); b_committed.set()

    left, right = threading.Thread(target=first), threading.Thread(target=second)
    left.start(); right.start(); left.join(timeout=2); right.join(timeout=2)
    current = store.get(session_id); assert current is not None
    assert current.coach_resolution_status == {"a": "accepted", "b": "accepted"}
    store.delete(session_id)
    store.persist_session(session_id)
    assert AnalysisSessionStore(persistence=SQLiteSessionPersistence(get_settings().session_db_path, ttl_hours=24)).get(session_id) is None


def test_different_live_sessions_do_not_share_a_logical_mutation_gate() -> None:
    store = AnalysisSessionStore(persistence=SQLiteSessionPersistence(get_settings().session_db_path, ttl_hours=24))
    first = store.create(AnalysisSession(profile=_profile(), quality=analyze_cv_quality(_profile()), coach=analyze_career_profile_gaps(_profile()), questions={}))
    second = store.create(AnalysisSession(profile=_profile(), quality=analyze_cv_quality(_profile()), coach=analyze_career_profile_gaps(_profile()), questions={}))
    first_entered, release_first, second_done = threading.Event(), threading.Event(), threading.Event()

    def mutate_first() -> None:
        session = store.get(first); assert session is not None
        first_entered.set(); assert release_first.wait(timeout=2)
        session.coach_resolution_status["first"] = "accepted"; store.persist_session(first)

    def mutate_second() -> None:
        assert first_entered.wait(timeout=2)
        session = store.get(second); assert session is not None
        session.coach_resolution_status["second"] = "accepted"; store.persist_session(second); second_done.set()

    left, right = threading.Thread(target=mutate_first), threading.Thread(target=mutate_second)
    left.start(); right.start(); assert second_done.wait(timeout=2)
    release_first.set(); left.join(timeout=2); right.join(timeout=2)
    assert store.get(first).coach_resolution_status == {"first": "accepted"}  # type: ignore[union-attr]
    assert store.get(second).coach_resolution_status == {"second": "accepted"}  # type: ignore[union-attr]
    store.delete(first); store.delete(second)


def test_expired_or_corrupt_persisted_session_is_never_hydrated() -> None:
    path = get_settings().session_db_path
    expired = AnalysisSessionStore(persistence=SQLiteSessionPersistence(path, ttl_hours=0))
    session_id = expired.create(AnalysisSession(profile=_profile(), quality=analyze_cv_quality(_profile()), coach=analyze_career_profile_gaps(_profile()), questions={}))
    assert AnalysisSessionStore(persistence=SQLiteSessionPersistence(path, ttl_hours=0)).get(session_id) is None

    corrupt = SQLiteSessionPersistence(path, ttl_hours=24)
    connection = corrupt._connect()
    try:
        connection.execute("INSERT INTO analysis_sessions VALUES (?, ?, ?, ?, ?, ?)", ("corrupt", 1, "not-json", "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"))
        connection.commit()
    finally:
        connection.close()
    assert AnalysisSessionStore(persistence=corrupt).get("corrupt") is None


def test_unaccepted_coach_answer_preserves_context_without_promoting_its_candidate() -> None:
    analysis = asyncio.run(_request(
        "POST", "/api/v1/cv/analyze",
        files={"file": ("candidate.pdf", _pdf("SKILLS", "- SAP"), "application/pdf")},
    )).json()
    session_id = analysis["session_id"]
    question = next(item for item in analysis["coach"]["questions"] if item["category"] == "certification")

    answer = asyncio.run(_request("POST", "/api/v1/cv/coach-answer", json={
        "session_id": session_id,
        "question_id": question["question_id"],
        "answer_text": "PMP",
    }))

    assert answer.status_code == 200
    assert answer.json()["candidate"]["verification_status"] == "inferred_unverified"
    assert session_store.get_unified_career_context(session_id) is not None
    assert session_store.get(session_id).profile == session_store.get(session_id).profile


def test_accepted_coach_candidate_rebuilds_context_and_refreshes_existing_job_state() -> None:
    first = asyncio.run(_request(
        "POST", "/api/v1/cv/analyze",
        files={"file": ("first.pdf", _pdf("candidate@example.com", "SKILLS", "- SAP"), "application/pdf")},
    )).json()
    second = asyncio.run(_request(
        "POST", "/api/v1/cv/analyze",
        files={"file": ("second.pdf", _pdf("SKILLS", "- Python"), "application/pdf")},
    )).json()
    session_id = first["session_id"]
    question = next(item for item in first["coach"]["questions"] if item["category"] == "certification")

    job = asyncio.run(_request("POST", "/api/v1/jobs/analyze", json={
        "session_id": session_id,
        "job_text": "Data Analyst\nPython and SQL",
    }))
    assert job.status_code == 200
    draft = asyncio.run(_request("POST", "/api/v1/cv/generate/review", json={
        "session_id": session_id,
        "mode": "general",
    }))
    assert draft.status_code == 200
    before_context = session_store.get_unified_career_context(session_id)
    answer = asyncio.run(_request("POST", "/api/v1/cv/coach-answer", json={
        "session_id": session_id,
        "question_id": question["question_id"],
        "answer_text": "PMP",
    })).json()

    assert session_store.get_unified_career_context(session_id) == before_context
    accepted = asyncio.run(_request("POST", "/api/v1/cv/coach-candidate/resolve", json={
        "session_id": session_id,
        "candidate_id": answer["candidate_id"],
        "action": "accept",
    }))

    assert accepted.status_code == 200
    payload = accepted.json()
    assert payload["context_rebuilt"] is True
    assert payload["job_results"]["job_analysis"] == job.json()["job_analysis"]
    context = session_store.get_unified_career_context(session_id)
    assert context is not None
    promoted = context.atomic_profile.additional_facts[-1]
    assert promoted.statement == "PMP"
    assert promoted.verification_status is VerificationStatus.USER_PROVIDED
    assert session_store.get(session_id).current_generated_draft is None
    assert session_store.get(session_id).job_context_revision == session_store.get(session_id).context_revision
    stale_decision = asyncio.run(_request("POST", "/api/v1/cv/generate/review/decision", json={
        "session_id": session_id,
        "draft_id": draft.json()["draft_id"],
        "item_id": draft.json()["items"][0]["item_id"],
        "decision": "remove",
    }))
    assert stale_decision.status_code == 409
    assert session_store.get_unified_career_context(second["session_id"]).atomic_profile.skills[0].statement == "Python"

import hashlib

from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.domain.document import CVDocument, SectionType, ParserConfidence
from app.domain.document.continuation import create_company_continuation_evidence
from app.parsers.pdf import (
    EmptyPDFInputError,
    EncryptedPDFError,
    InvalidPDFError,
    NoMachineReadableTextError,
    PDFInputTooLargeError,
    PDFPageLimitExceededError,
    PDFParserError,
    parse_pdf,
)
from app.extraction.career import extract_career_profile
from app.services.cv_quality_analysis.service import analyze_cv_quality
from app.services.cv_quality_analysis import analyze_reviewed_cv_quality
from app.services.career_gap_analysis.service import analyze_career_profile_gaps
from app.services.coach_answer_processing import CoachAnswer, process_coach_answer
from app.services.analysis_session import AnalysisSession, AnalysisSessionStore
from app.services.analysis_session.service import ContinuationCandidateState
from app.services.analysis_session.service import active_unresolved_evidence, readiness_evidence_id
from app.services.analysis_session.schemas import (
    CoachAnswerRequest, CoachCandidateResolutionRequest,
    ContinuationCandidateResolutionRequest, ContinuationResolutionAction,
    SessionRecoveryRequest,
    SessionDeletionRequest,
    ReadinessResolutionRequest,
)
from app.core.config import get_settings
from app.confirmation.structured import (
    StructuredFieldAction, TextFieldDecision, WholeRecordAction,
    WorkExperienceFieldDecisions, create_work_experience_candidate,
    resolve_work_experience_candidate,
)
from app.domain.career import FactSource, ProvenancedText, SourceType, VerificationStatus, WorkExperience
from app.confirmation.career import resolve_candidate
from app.confirmation.career.schemas import ResolutionStatus
from app.confirmation.career.service import candidate_id
from app.services.analysis_session.schemas import CoverLetterDecisionRequest, CoverLetterExportRequest, CoverLetterRequest, CoverLetterRewriteRequest, CvQualityRequest, CvValidationRequest, DocxExportRequest, GenerationReviewDecisionRequest, GenerationRewriteRequest, GenerationReviewRequest, PdfExportRequest
from app.services.career_context import build_analyzed_unified_career_context
from app.services.generation_workflow import GenerationWorkflowError, generate_draft_from_context
from app.services.generation_strategy import GenerationMode
from app.services.draft_review import reviewed_draft
from app.services.controlled_rewrite import ControlledRewriteError, controlled_rewrite
from app.ai.providers import OpenAIProvider, OpenAIProviderError
from app.services.docx_export import DocxExportError, export_reviewed_draft
from app.services.pdf_export import PdfExportError, export_pdf
from app.services.public_cv_projection import build_public_cv_projection
from app.services.cv_validation import validate_cv
from app.services.generation_context import build_generation_context
from app.services.cover_letter import CoverLetterDecision, generate_cover_letter, review_cover_letter
from app.services.cover_letter.rewrite.service import enhance_cover_letter_wording
from app.services.cover_letter_export import CoverLetterDocxExportError, CoverLetterPdfExportError, export_cover_letter_docx, export_cover_letter_pdf
from app.services.public_cover_letter_projection import build_public_cover_letter_projection
from app.services.profile_readiness import ReadinessStatus, assess_unified_career_readiness
from app.services.job_match import match_job_to_profile
from app.services.job_match_score import calculate_job_match_score
from app.services.job_coach import generate_job_specific_coach_questions
from app.services.draft_review import ReviewedCvDraft
from app.services.cover_letter import ReviewedCoverLetter
from app.services.cv_validation import CvValidationReport

router = APIRouter(prefix="/cv", tags=["cv"])
session_store = AnalysisSessionStore()


_INTERNAL_PUBLIC_FIELDS = frozenset({
    "association_evidence_id",
    "block_id",
    "block_ids",
    "evidence_references",
    "identity",
    "lineage_id",
    "matched_evidence_references",
    "parser_block_id",
    "source",
    "source_reference",
    "source_references",
    "job_source_references",
})


def _scrub_public_payload(value: Any) -> Any:
    """Remove server-only provenance and storage fields from public JSON."""
    if isinstance(value, dict):
        return {key: _scrub_public_payload(item) for key, item in value.items() if key not in _INTERNAL_PUBLIC_FIELDS}
    if isinstance(value, list):
        return [_scrub_public_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_public_payload(item) for item in value)
    return value


def _public_job_match(match) -> dict:
    """Return job results without exposing server-side evidence lineage."""
    return _scrub_public_payload(match.model_dump(mode="json"))


def _rebuild_context_after_profile_change(session_id: str, session) -> dict | None:
    """Reassemble only server-owned state; do not parse, infer, or call AI."""
    job_analysis = session.job_analysis
    context = build_analyzed_unified_career_context(
        profile=session.profile,
        unresolved_evidence=active_unresolved_evidence(session),
        work_results=tuple(session.continuation_resolutions.values()),
    )
    refreshed = session_store.set_unified_career_context(
        session_id,
        context=context,
        preserve_job_analysis=job_analysis is not None,
    )
    assert refreshed is not None
    if job_analysis is None:
        return None
    match = match_job_to_profile(job_analysis.profile, refreshed.profile, job_analysis.unresolved_items)
    score = calculate_job_match_score(match)
    coach = generate_job_specific_coach_questions(job_analysis.profile, match)
    session_store.set_job_results(
        session_id,
        job_analysis=job_analysis,
        job_match=match,
        job_score=score,
        job_coach=coach,
    )
    return {
        "job_analysis": job_analysis.model_dump(mode="json"),
        "job_match": _public_job_match(match),
        "job_score": score.model_dump(mode="json"),
        "job_coach": coach.model_dump(mode="json"),
    }


def _continuation_states(document: CVDocument, extraction) -> tuple[ContinuationCandidateState, ...]:
    """Produce only same-column, same-section unverified continuation proposals."""
    blocks = {block.stable_reference: block for block in document.blocks}
    experience_sections = [section for section in document.sections if section.section_type is SectionType.EXPERIENCE]
    states: list[ContinuationCandidateState] = []
    for candidate in extraction.work_experience_candidates:
        if candidate.company is not None or candidate.title is None or candidate.start_date is None:
            continue
        current_refs = tuple(source.reference for source in candidate.origin.evidence_sources)
        current_block = blocks.get(candidate.title.value_source.reference)
        if current_block is None:
            continue
        section = next((item for item in experience_sections if current_block.stable_reference in item.block_references), None)
        if section is None:
            continue
        # ``block_index`` is page-local.  Filter the parsed document by page
        # before comparing it so a page-two role cannot accidentally inspect
        # an unrelated global block slice.
        preceding_in_column = (
            block
            for block in document.blocks
            if block.location.page_number == current_block.location.page_number
            and block.location.column_index == current_block.location.column_index
            and block.location.block_index < current_block.location.block_index
            and block.stable_reference in section.block_references
        )
        prior = next(
            (
                block
                for block in reversed(tuple(preceding_in_column))
                if any(block.raw_text.strip() == role.company for role in extraction.profile.work_experiences)
            ),
            None,
        )
        if prior is None:
            continue
        evidence = create_company_continuation_evidence(
            proposed_company=prior.raw_text.strip(), previous_company_reference=prior.stable_reference,
            current_role_references=current_refs, section_reference=section.block_references[0], confidence=ParserConfidence.HIGH,
        )
        states.append(ContinuationCandidateState(work_candidate=candidate, evidence=evidence))
    return tuple(states)


def _public_continuation_candidates(session) -> tuple[dict[str, str], ...]:
    """Return actionable text only; parser and record internals remain server-side."""
    return tuple(
        {
            "candidate_id": candidate_id,
            "question": "Bu pozisyon önceki şirketle devam ediyor olabilir.",
            "proposed_company": state.evidence.proposed_company,
            "reason": "Önceki açık şirket bilgisi ve belge sırası bu öneriyi destekliyor.",
            "potential_impact": "Onaylanırsa bu pozisyon güvenli CV üretiminde kullanılabilir.",
        }
        for candidate_id, state in session.continuation_candidates.items()
        if candidate_id not in session.continuation_resolutions
    )


def _review_item_id(category: str, internal_id: str) -> str:
    """Stable public identifier; never expose the underlying candidate key."""
    value = hashlib.sha256(f"career-review:{category}:{internal_id}".encode("utf-8")).hexdigest()
    return f"review:{value}"


def _review_status_from_continuation(result) -> str:
    if result is None:
        return "NEEDS_REVIEW"
    if result.status.value == "resolved":
        return "ACCEPTED"
    if result.status.value == "rejected":
        return "REJECTED"
    return "UNRESOLVED"


def _career_profile_review(session) -> dict:
    """One public, deterministic view over isolated confirmation backends."""
    items: list[dict[str, object]] = []
    for internal_id, state in session.continuation_candidates.items():
        state_result = session.continuation_resolutions.get(internal_id)
        items.append({
            "item_id": _review_item_id("continuation", internal_id),
            "category": "WORK_EXPERIENCE_COMPANY",
            "title": state.work_candidate.title.value if state.work_candidate.title else "İş deneyimi",
            "question": "CV'nizde bu pozisyonun şirket bilgisi eksik görünüyor.",
            "proposed_value": state.evidence.proposed_company,
            "reason": "Önceki açık şirket bilgisi ve belge sırası bu öneriyi destekliyor.",
            "potential_impact": "Work Experience bölümündeki şirket adı.",
            "status": _review_status_from_continuation(state_result),
            "actions": ("ACCEPT", "CORRECT", "REJECT", "LEAVE_UNRESOLVED") if state_result is None else (),
        })
    for internal_id, candidate in session.coach_candidates.items():
        resolved = session.coach_resolution_status.get(internal_id)
        items.append({
            "item_id": _review_item_id("coach", internal_id),
            "category": "CAREER_FACT",
            "title": "Kariyer bilgisi",
            "question": "Bu bilgiyi kariyer profilinize eklemek ister misiniz?",
            "proposed_value": candidate.proposed_statement,
            "reason": "Bu bilgi verdiğiniz Coach yanıtından oluşturuldu.",
            "potential_impact": "Kariyer profilindeki doğrulanmış bilgiler.",
            "status": resolved or "NEEDS_REVIEW",
            "actions": ("ACCEPT", "CORRECT", "REJECT") if resolved is None else (),
        })
    priority = {"WORK_EXPERIENCE_COMPANY": 0, "CAREER_FACT": 6}
    items.sort(key=lambda item: (priority.get(str(item["category"]), 99), str(item["title"]), str(item["item_id"])))
    context = session.unified_career_context
    readiness = assess_unified_career_readiness(context) if context is not None else None
    pending = sum(item["status"] == "NEEDS_REVIEW" for item in items)
    return {
        "items": tuple(items),
        "summary": {"needs_review_count": pending, "profile_status": "PROFILE_READY" if readiness and readiness.status is ReadinessStatus.READY else "NEEDS_REVIEW"},
        "readiness": _public_readiness(session, readiness),
    }


def _public_readiness(session, readiness) -> dict:
    """Expose actionable readiness state without source coordinates or text."""
    active = active_unresolved_evidence(session)
    items = tuple({
        "finding_id": readiness_evidence_id(item),
        "category": "UNRESOLVED_SOURCE_ITEM",
        "message": "CV'nizde güvenle yapılandırılamayan bir bilgi var. Bu bilgiyi taslağa dahil etmeyerek devam edebilirsiniz.",
        "blocking": True,
        "actions": ("REJECT",),
    } for item in active)
    if readiness is not None and readiness.status is not ReadinessStatus.READY and not items:
        items = ({
            "finding_id": "readiness:non-resolvable",
            "category": "READINESS_REVIEW",
            "message": "CV'nizde taslak oluşturmadan önce güvenle çözülemeyen bir kontrol bulunuyor. Bu durum için otomatik bir işlem yapılamaz.",
            "blocking": True,
            "actions": (),
        },)
    return {"status": readiness.status.value if readiness is not None else "blocked", "items": items}


def _internal_continuation_id(session, public_id: str) -> str | None:
    return next((key for key in session.continuation_candidates if _review_item_id("continuation", key) == public_id), None)


def _internal_coach_id(session, public_id: str) -> str | None:
    return next((key for key in session.coach_candidates if _review_item_id("coach", key) == public_id), None)


def _candidate_with_server_proposal(state: ContinuationCandidateState):
    """Give the existing resolver a proposed field without trusting geometry."""
    candidate = state.work_candidate
    proposed_company = ProvenancedText(
        value=state.evidence.proposed_company,
        verification_status=VerificationStatus.INFERRED_UNVERIFIED,
        value_source=FactSource(
            source_type=SourceType.MASTER_CV,
            reference=state.evidence.previous_company_reference,
            original_text=state.evidence.proposed_company,
        ),
    )
    return create_work_experience_candidate(
        origin=candidate.origin,
        company=proposed_company,
        title=candidate.title,
        location=candidate.location,
        start_date=candidate.start_date,
        end_date=candidate.end_date,
        is_current=candidate.is_current,
    )


def _profile_work_experience(result) -> WorkExperience:
    record = result.resolved_record
    assert record is not None and record.company is not None and record.title is not None and record.start_date is not None
    return WorkExperience(
        company=record.company.value,
        title=record.title.value,
        location=record.location.value if record.location else None,
        start_date=record.start_date.value,
        end_date=record.end_date.value if record.end_date else None,
        is_current=record.is_current.value if record.is_current else False,
        date_range_open=not bool(record.end_date),
    )


class CVSectionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: SectionType
    original_heading: str | None = None
    block_count: int = Field(ge=1)


class CVParseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["parsed"] = "parsed"
    filename: str
    page_count: int = Field(ge=1)
    block_count: int = Field(ge=1)
    sections: tuple[CVSectionSummary, ...]


class PublicQualityFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    dimension: str
    severity: str
    message: str
    score_impact: int
    remediation_hint: str | None = None


class PublicQualityDimension(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    score: int
    max_score: int
    is_evaluated: bool
    reason_codes: tuple[str, ...] = ()


class PublicQualityResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    overall_score: int
    dimensions: tuple[PublicQualityDimension, ...]
    findings: tuple[PublicQualityFinding, ...] = ()
    strengths: tuple[PublicQualityFinding, ...] = ()
    improvement_opportunities: tuple[PublicQualityFinding, ...] = ()


class PublicCoachQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str
    category: str
    question_text: str
    reason: str
    target_section: str
    priority: str
    missing_signal: str
    answer_type: str
    related_role: str | None = None
    question_type: str | None = None
    related_requirement_id: str | None = None
    expected_information: str | None = None
    potential_impact: str | None = None
    status: str


class PublicCoachResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    questions: tuple[PublicCoachQuestion, ...] = ()
    total_recommendations: int
    more_recommendations_available: bool


class CareerProfileReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[dict[str, Any], ...] = ()
    summary: dict[str, Any]
    readiness: dict[str, Any]


class CVAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    parse: CVParseResponse
    profile: dict[str, Any]
    quality: PublicQualityResponse
    coach: PublicCoachResponse
    career_profile_review: CareerProfileReviewResponse


class SessionRecoveryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    profile: dict[str, Any]
    quality: PublicQualityResponse
    coach: PublicCoachResponse
    career_profile_review: CareerProfileReviewResponse
    job_results: dict[str, Any] | None = None
    generation_ready: bool


class SessionDeletionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["deleted"] = "deleted"


class ContinuationResolutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    candidate_id: str
    message: str


class CoachAnswerResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_question_id: str
    status: str
    issue_codes: tuple[str, ...] = ()
    candidate: dict[str, Any] | None = None
    candidate_id: str | None = None


class CoachCandidateResolutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    issue_codes: tuple[str, ...] = ()
    context_rebuilt: bool = False
    profile: dict[str, Any] | None = None
    career_profile_review: CareerProfileReviewResponse | None = None
    job_results: dict[str, Any] | None = None


class ReadinessResolutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["resolved"] = "resolved"
    career_profile_review: CareerProfileReviewResponse
    job_results: dict[str, Any] | None = None


class GeneratedQualityResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    score: int
    dimensions: tuple[dict[str, Any], ...]
    strengths: tuple[dict[str, Any], ...]
    improvement_opportunities: tuple[dict[str, Any], ...]


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _map_parser_error(error: PDFParserError) -> HTTPException:
    if isinstance(error, EmptyPDFInputError):
        return _api_error(status.HTTP_400_BAD_REQUEST, "empty_pdf", "The PDF file is empty.")
    if isinstance(error, PDFInputTooLargeError):
        return _api_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "pdf_too_large",
            "The PDF exceeds the allowed file size.",
        )
    if isinstance(error, PDFPageLimitExceededError):
        return _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "pdf_page_limit_exceeded", "The PDF exceeds the allowed page limit.")
    if isinstance(error, EncryptedPDFError):
        return _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "encrypted_pdf",
            "Password-protected PDFs are not supported.",
        )
    if isinstance(error, NoMachineReadableTextError):
        return _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "no_machine_readable_text",
            "No machine-readable text was found in the PDF.",
        )
    if isinstance(error, InvalidPDFError):
        return _api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_pdf",
            "The file could not be read as a valid PDF.",
        )
    return _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "pdf_parse_failed", "The PDF could not be parsed.")


async def _read_pdf_upload(file: UploadFile) -> bytes:
    """Bound multipart buffering before parser work starts."""
    limit = get_settings().pdf_max_bytes
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise PDFInputTooLargeError("PDF input exceeds the configured parser limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _to_response(document: CVDocument) -> CVParseResponse:
    return CVParseResponse(
        filename=document.source.filename,
        page_count=document.source.page_count or len(document.pages),
        block_count=len(document.blocks),
        sections=tuple(
            CVSectionSummary(
                type=section.section_type,
                original_heading=section.original_heading,
                block_count=len(section.block_references),
            )
            for section in document.sections
        ),
    )


def _public_profile(profile) -> dict:
    """UI data is useful without exposing internal parser block references."""
    return _scrub_public_payload(profile.model_dump(mode="json"))


def _public_quality(quality) -> dict:
    return _scrub_public_payload(quality.model_dump(mode="json"))


def _public_coach(coach) -> dict:
    payload = coach.model_dump(mode="json")
    return {
        "questions": tuple(_scrub_public_payload(question) for question in payload["questions"]),
        "total_recommendations": payload["total_recommendations"],
        "more_recommendations_available": payload["more_recommendations_available"],
    }


@router.post("/parse", response_model=CVParseResponse)
async def parse_cv_pdf(
    file: UploadFile | None = File(default=None),
) -> CVParseResponse:
    """Parse one uploaded text PDF and return a small, safe UI summary."""

    if file is None:
        raise _api_error(status.HTTP_400_BAD_REQUEST, "missing_file", "A PDF file is required.")
    if file.content_type != "application/pdf" or not (file.filename or "").lower().endswith(".pdf"):
        raise _api_error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported_file_type",
            "Only PDF files are supported.",
        )

    try:
        return _to_response(parse_pdf(await _read_pdf_upload(file), file.filename, max_file_size=get_settings().pdf_max_bytes, max_page_count=get_settings().pdf_max_pages))
    except PDFParserError as error:
        raise _map_parser_error(error) from error
    finally:
        await file.close()


@router.post("/analyze", response_model=CVAnalysisResponse)
async def analyze_cv_pdf(file: UploadFile | None = File(default=None)) -> CVAnalysisResponse:
    """Run the existing deterministic profile, quality, and coach services for one PDF."""
    if file is None:
        raise _api_error(status.HTTP_400_BAD_REQUEST, "missing_file", "A PDF file is required.")
    if file.content_type != "application/pdf" or not (file.filename or "").lower().endswith(".pdf"):
        raise _api_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "unsupported_file_type", "Only PDF files are supported.")
    try:
        document = parse_pdf(await _read_pdf_upload(file), file.filename, max_file_size=get_settings().pdf_max_bytes, max_page_count=get_settings().pdf_max_pages)
        extraction = extract_career_profile(document)
        quality = analyze_cv_quality(extraction.profile, document=document, unresolved_evidence=extraction.unresolved_evidence)
        coach = analyze_career_profile_gaps(extraction.profile)
        unified_career_context = build_analyzed_unified_career_context(
            profile=extraction.profile,
            unresolved_evidence=extraction.unresolved_evidence,
        )
        session_id = session_store.create(AnalysisSession(
            profile=extraction.profile,
            quality=quality,
            coach=coach,
            questions={item.question_id: item for item in coach.questions},
            unified_career_context=unified_career_context,
            unresolved_evidence=extraction.unresolved_evidence,
        ))
        session_store.set_continuation_candidates(session_id, candidates=_continuation_states(document, extraction))
        session = session_store.get(session_id)
        assert session is not None
        return CVAnalysisResponse(
            session_id=session_id,
            parse=_to_response(document),
            profile=_public_profile(extraction.profile),
            quality=PublicQualityResponse.model_validate(_public_quality(quality)),
            coach=PublicCoachResponse.model_validate(_public_coach(coach)),
            career_profile_review=CareerProfileReviewResponse.model_validate(_career_profile_review(session)),
        )
    except PDFParserError as error:
        raise _map_parser_error(error) from error
    finally:
        await file.close()


@router.post("/session/recover", response_model=SessionRecoveryResponse)
def recover_session(payload: SessionRecoveryRequest) -> SessionRecoveryResponse:
    """Hydrate a persisted session without exposing persistence metadata."""
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before recovering this session.")
    job_results = None
    if session.job_analysis is not None and session.job_match is not None and session.job_score is not None and session.job_coach is not None:
        job_results = {
            "job_analysis": _scrub_public_payload(session.job_analysis.model_dump(mode="json")),
            "job_match": _public_job_match(session.job_match),
            "job_score": _scrub_public_payload(session.job_score.model_dump(mode="json")),
            "job_coach": _scrub_public_payload(session.job_coach.model_dump(mode="json")),
        }
    return SessionRecoveryResponse(
        session_id=payload.session_id,
        profile=_public_profile(session.profile),
        quality=PublicQualityResponse.model_validate(_public_quality(session.quality)),
        coach=PublicCoachResponse.model_validate(_public_coach(session.coach)),
        career_profile_review=CareerProfileReviewResponse.model_validate(_career_profile_review(session)),
        job_results=job_results,
        generation_ready=session.unified_career_context is not None,
    )


@router.post("/session/delete", response_model=SessionDeletionResponse)
def delete_session(payload: SessionDeletionRequest) -> SessionDeletionResponse:
    """Forget one opaque session from memory and durable runtime storage."""
    session_store.delete(payload.session_id)
    return SessionDeletionResponse()


@router.post("/continuation-candidate/resolve", response_model=ContinuationResolutionResponse)
def resolve_continuation_candidate(payload: ContinuationCandidateResolutionRequest) -> ContinuationResolutionResponse:
    """Resolve exactly one server-issued company-continuation proposal."""
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before resolving a continuation proposal.")
    internal_id = _internal_continuation_id(session, payload.candidate_id)
    state = session.continuation_candidates.get(internal_id) if internal_id else None
    if state is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "continuation_candidate_not_found", "This continuation proposal is not available in the current session.")
    if internal_id in session.continuation_resolutions:
        raise _api_error(status.HTTP_409_CONFLICT, "continuation_candidate_already_resolved", "This continuation proposal was already resolved.")

    if payload.action is ContinuationResolutionAction.ACCEPT:
        result = resolve_work_experience_candidate(
            _candidate_with_server_proposal(state),
            WorkExperienceFieldDecisions(company=TextFieldDecision(action=StructuredFieldAction.ACCEPT)),
            user_input_reference=f"continuation:{internal_id}",
        )
    elif payload.action is ContinuationResolutionAction.CORRECT:
        result = resolve_work_experience_candidate(
            state.work_candidate,
            WorkExperienceFieldDecisions(company=TextFieldDecision(action=StructuredFieldAction.CORRECT, corrected_value=payload.correction.strip())),
            user_input_reference=f"continuation:{internal_id}",
        )
    elif payload.action is ContinuationResolutionAction.REJECT:
        result = resolve_work_experience_candidate(
            state.work_candidate, WorkExperienceFieldDecisions(), whole_record_action=WholeRecordAction.REJECT_RECORD,
        )
    else:
        result = resolve_work_experience_candidate(state.work_candidate, WorkExperienceFieldDecisions())

    if session_store.resolve_continuation_candidate(payload.session_id, candidate_id=internal_id, result=result) is None:
        raise _api_error(status.HTTP_409_CONFLICT, "continuation_candidate_stale", "Analyze the CV again before resolving this proposal.")

    if result.resolved_record is not None and result.status.value == "resolved":
        session.profile = session.profile.model_copy(update={"work_experiences": session.profile.work_experiences + (_profile_work_experience(result),)})
    context = build_analyzed_unified_career_context(
        profile=session.profile,
        unresolved_evidence=active_unresolved_evidence(session),
        work_results=tuple(session.continuation_resolutions.values()),
    )
    session_store.set_unified_career_context(payload.session_id, context=context)
    return ContinuationResolutionResponse(
        status=result.status.value,
        candidate_id=payload.candidate_id,
        message="Continuation decision saved. CV context was refreshed.",
    )


@router.post("/career-profile-review", response_model=CareerProfileReviewResponse)
def career_profile_review(payload: SessionRecoveryRequest) -> CareerProfileReviewResponse:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before reviewing the profile.")
    return CareerProfileReviewResponse.model_validate(_career_profile_review(session))


@router.post("/readiness/resolve", response_model=ReadinessResolutionResponse)
def resolve_readiness_item(payload: ReadinessResolutionRequest) -> ReadinessResolutionResponse:
    """Apply only a server-authorized omission of one unresolved source item."""
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before resolving readiness.")
    if payload.finding_id in session.readiness_rejected_evidence_ids:
        raise _api_error(status.HTTP_409_CONFLICT, "readiness_finding_already_resolved", "This readiness item was already resolved.")
    if not any(readiness_evidence_id(item) == payload.finding_id for item in active_unresolved_evidence(session)):
        raise _api_error(status.HTTP_404_NOT_FOUND, "readiness_finding_not_found", "This readiness item is not available in the current session.")
    if session_store.reject_readiness_evidence(payload.session_id, finding_id=payload.finding_id) is None:
        raise _api_error(status.HTTP_409_CONFLICT, "readiness_finding_stale", "This readiness item is no longer available.")
    session = session_store.get(payload.session_id)
    assert session is not None
    job_results = _rebuild_context_after_profile_change(payload.session_id, session)
    return ReadinessResolutionResponse(
        career_profile_review=CareerProfileReviewResponse.model_validate(_career_profile_review(session)),
        job_results=_scrub_public_payload(job_results) if job_results is not None else None,
    )


@router.post("/coach-answer", response_model=CoachAnswerResponse)
def process_answer(payload: CoachAnswerRequest) -> CoachAnswerResponse:
    """Process a stored coach question without promoting user input to verified facts."""
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before saving a coach answer.")
    question = session.questions.get(payload.question_id)
    if question is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "coach_question_not_found", "This coach question is not available in the current analysis session.")
    result = process_coach_answer(question, CoachAnswer(question_id=payload.question_id, answer_text=payload.answer_text))
    if result.candidate is not None:
        proposal_id = candidate_id(result.candidate)
        session_store.set_coach_candidate(payload.session_id, candidate_id=proposal_id, candidate=result.candidate)
        candidate = result.candidate.model_dump(mode="json")
        return CoachAnswerResponse(
            source_question_id=result.source_question_id,
            status=result.status.value,
            issue_codes=result.issue_codes,
            candidate=_scrub_public_payload(candidate),
            candidate_id=_review_item_id("coach", proposal_id),
        )
    # An unanswered or deferred response cannot affect the canonical profile
    # or its context. The candidate remains isolated until explicit ACCEPT.
    return CoachAnswerResponse(
        source_question_id=result.source_question_id,
        status=result.status.value,
        issue_codes=result.issue_codes,
    )


@router.post("/coach-candidate/resolve", response_model=CoachCandidateResolutionResponse)
def resolve_coach_candidate(payload: CoachCandidateResolutionRequest) -> CoachCandidateResolutionResponse:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before resolving a coach proposal.")
    internal_id = _internal_coach_id(session, payload.candidate_id)
    candidate = session.coach_candidates.get(internal_id) if internal_id else None
    if candidate is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "coach_candidate_not_found", "This coach proposal is not available in the current session.")
    result = resolve_candidate(candidate, payload.action, correction=payload.correction, resolved_candidate_ids=frozenset(session.resolved_candidate_ids))
    if result.status is ResolutionStatus.PROMOTED and result.promoted_fact is not None:
        fact = result.promoted_fact
        update = {"skills": session.profile.skills + (fact,)} if fact.skills else {"tools": session.profile.tools + (fact,)} if fact.tools else {"additional_facts": session.profile.additional_facts + (fact,)}
        session.profile = session.profile.model_copy(update=update)
        session.resolved_candidate_ids.add(internal_id)
        session.coach_resolution_status[internal_id] = "ACCEPTED"
        job_results = _rebuild_context_after_profile_change(payload.session_id, session)
        return CoachCandidateResolutionResponse(
            status=result.status.value,
            issue_codes=result.issue_codes,
            context_rebuilt=True,
            profile=_public_profile(session.profile),
            career_profile_review=CareerProfileReviewResponse.model_validate(_career_profile_review(session)),
            job_results=_scrub_public_payload(job_results) if job_results is not None else None,
        )
    elif result.status is ResolutionStatus.REJECTED:
        session.resolved_candidate_ids.add(internal_id)
        session.coach_resolution_status[internal_id] = "REJECTED"
        session_store.persist_session(payload.session_id)
    return CoachCandidateResolutionResponse(status=result.status.value, issue_codes=result.issue_codes)


@router.post("/generate/review", response_model=ReviewedCvDraft)
def generate_review(payload: GenerationReviewRequest) -> ReviewedCvDraft:
    """Return a public deterministic draft review from stored analysis state."""

    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before generating a review.")
    context = session_store.get_unified_career_context(payload.session_id)
    if context is None:
        raise _api_error(status.HTTP_409_CONFLICT, "unified_context_unavailable", "Analyze the CV again before generating a review.")
    if payload.mode is GenerationMode.TARGETED and not session_store.has_current_job_match(payload.session_id):
        raise _api_error(status.HTTP_409_CONFLICT, "targeted_job_state_missing", "Analyze a job listing for the current CV before targeted generation.")
    try:
        draft = generate_draft_from_context(
            context=context,
            mode=payload.mode,
            job_match=session.job_match if payload.mode is GenerationMode.TARGETED else None,
        )
    except GenerationWorkflowError as error:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code, str(error)) from error
    current = reviewed_draft(draft)
    session_store.set_generated_draft(payload.session_id, draft=draft, draft_id=current.draft_id)
    return current


@router.post("/generate/review/decision", response_model=ReviewedCvDraft)
def decide_generated_review(payload: GenerationReviewDecisionRequest) -> ReviewedCvDraft:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before reviewing a draft.")
    if session.current_generated_draft is None or session.current_draft_id != payload.draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current CV draft again before deciding.")
    current = reviewed_draft(session.current_generated_draft, session.draft_decisions.get(payload.draft_id, {}))
    known_ids = {item.item_id for item in current.items}
    if payload.item_id not in known_ids:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_draft_item", "This item is not available in the current draft.")
    session_store.set_draft_decision(payload.session_id, draft_id=payload.draft_id, item_id=payload.item_id, decision=payload.decision)
    return reviewed_draft(session.current_generated_draft, session.draft_decisions[payload.draft_id], session.draft_rewrites.get(payload.draft_id, {}))


@router.post("/generate/review/rewrite", response_model=ReviewedCvDraft)
def rewrite_generated_review(payload: GenerationRewriteRequest) -> ReviewedCvDraft:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before rewriting a draft.")
    if session.current_generated_draft is None or session.current_draft_id != payload.draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current CV draft again before rewriting.")
    current = reviewed_draft(session.current_generated_draft, session.draft_decisions.get(payload.draft_id, {}), session.draft_rewrites.get(payload.draft_id, {}))
    item = next((value for value in current.items if value.item_id == payload.item_id), None)
    if item is None:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_draft_item", "This item is not available in the current draft.")
    if item.decision.value == "remove":
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "removed_item", "A removed draft item cannot be rewritten.")
    if item.section.value != "skill":
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "unsupported_rewrite_item", "Only standalone generated claims can be rewritten.")
    try:
        outcome = controlled_rewrite(OpenAIProvider(), original=item.text, mode=session.current_generated_draft.mode.value)
    except ControlledRewriteError as error:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code, "The rewrite could not be validated safely.") from error
    except OpenAIProviderError as error:
        raise _api_error(status.HTTP_503_SERVICE_UNAVAILABLE, "rewrite_unavailable", "Rewrite service is currently unavailable.") from error
    session_store.set_draft_rewrite(payload.session_id, draft_id=payload.draft_id, item_id=payload.item_id, text=outcome.rewritten_text)
    return reviewed_draft(session.current_generated_draft, session.draft_decisions.get(payload.draft_id, {}), session.draft_rewrites[payload.draft_id])


@router.post("/generate/export/docx")
def export_generated_docx(payload: DocxExportRequest) -> Response:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before exporting a draft.")
    if session.current_generated_draft is None or session.current_draft_id != payload.draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current CV draft again before exporting.")
    reviewed = reviewed_draft(session.current_generated_draft, session.draft_decisions.get(payload.draft_id, {}), session.draft_rewrites.get(payload.draft_id, {}))
    projection = build_public_cv_projection(profile=session.profile, reviewed_draft=reviewed)
    try:
        content = export_reviewed_draft(projection)
    except DocxExportError as error:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "docx_export_failed", "The reviewed draft could not be exported safely.") from error
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": 'attachment; filename="CV.docx"'})


@router.post("/generate/export/pdf")
def export_generated_pdf(payload: PdfExportRequest) -> Response:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before exporting a draft.")
    if session.current_generated_draft is None or session.current_draft_id != payload.draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current CV draft again before exporting.")
    reviewed = reviewed_draft(session.current_generated_draft, session.draft_decisions.get(payload.draft_id, {}), session.draft_rewrites.get(payload.draft_id, {}))
    projection = build_public_cv_projection(profile=session.profile, reviewed_draft=reviewed)
    try:
        content = export_pdf(projection)
    except PdfExportError as error:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "pdf_export_failed", "The reviewed draft could not be exported safely.") from error
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="CV.pdf"'})


@router.post("/generate/validate", response_model=CvValidationReport)
def validate_generated_cv(payload: CvValidationRequest) -> CvValidationReport:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before validating a draft.")
    if session.current_generated_draft is None or session.current_draft_id != payload.draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current CV draft again before validating.")
    if session.unified_career_context is None:
        raise _api_error(status.HTTP_409_CONFLICT, "unified_context_unavailable", "Analyze the CV again before validating.")
    decisions = session.draft_decisions.get(payload.draft_id, {})
    rewrites = session.draft_rewrites.get(payload.draft_id, {})
    reviewed = reviewed_draft(session.current_generated_draft, decisions, rewrites)
    projection = build_public_cv_projection(profile=session.profile, reviewed_draft=reviewed)
    report = validate_cv(
        projection=projection,
        draft=session.current_generated_draft,
        context=build_generation_context(session.unified_career_context),
        decisions=decisions,
        rewrites=rewrites,
    )
    return report


@router.post("/generate/quality", response_model=GeneratedQualityResponse)
def quality_generated_cv(payload: CvQualityRequest) -> GeneratedQualityResponse:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before scoring a draft.")
    if session.current_generated_draft is None or session.current_draft_id != payload.draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current CV draft again before scoring.")
    reviewed = reviewed_draft(session.current_generated_draft, session.draft_decisions.get(payload.draft_id, {}), session.draft_rewrites.get(payload.draft_id, {}))
    projection = build_public_cv_projection(profile=session.profile, reviewed_draft=reviewed)
    result = analyze_reviewed_cv_quality(session.profile, projection)
    return GeneratedQualityResponse(
        score=result.overall_score,
        dimensions=tuple({"name": item.dimension.value, "score": item.score, "max_score": item.max_score, "is_evaluated": item.is_evaluated} for item in result.dimensions),
        strengths=tuple({"code": item.code, "message": item.message} for item in result.strengths),
        improvement_opportunities=tuple({"code": item.code, "message": item.message} for item in result.improvement_opportunities),
    )


@router.post("/generate/cover-letter", response_model=ReviewedCoverLetter)
def generate_targeted_cover_letter(payload: CoverLetterRequest) -> ReviewedCoverLetter:
    if payload.mode is not GenerationMode.TARGETED:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "targeted_cover_letter_required", "Cover letters are available only for targeted generation.")
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before generating a cover letter.")
    if not session_store.has_current_job_match(payload.session_id) or session.job_analysis is None or session.unified_career_context is None:
        raise _api_error(status.HTTP_409_CONFLICT, "targeted_job_state_missing", "Analyze a job listing for the current CV before generating a cover letter.")
    try:
        targeted = generate_draft_from_context(context=session.unified_career_context, mode=GenerationMode.TARGETED, job_match=session.job_match)
    except GenerationWorkflowError as error:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code, str(error)) from error
    job = session.job_analysis.profile
    draft = generate_cover_letter(target_role=job.title, target_company=job.company, targeted_draft=targeted)
    session_store.set_cover_letter(payload.session_id, draft=draft)
    return review_cover_letter(draft)


@router.post("/generate/cover-letter/decision", response_model=ReviewedCoverLetter)
def decide_cover_letter(payload: CoverLetterDecisionRequest) -> ReviewedCoverLetter:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before reviewing a cover letter.")
    if session.current_cover_letter is None or session.current_cover_letter_id != payload.draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current cover letter again before deciding.")
    if payload.item_id not in {item.item_id for item in session.current_cover_letter.claims}:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_cover_letter_item", "This item is not available in the current cover letter.")
    session_store.set_cover_letter_decision(payload.session_id, draft_id=payload.draft_id, item_id=payload.item_id, decision=CoverLetterDecision(payload.decision.value))
    return review_cover_letter(session.current_cover_letter, session.cover_letter_decisions[payload.draft_id], session.cover_letter_rewrites.get(payload.draft_id, {}))


@router.post("/generate/cover-letter/rewrite", response_model=ReviewedCoverLetter)
def rewrite_cover_letter(payload: CoverLetterRewriteRequest) -> ReviewedCoverLetter:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before rewriting a cover letter.")
    if session.current_cover_letter is None or session.current_cover_letter_id != payload.draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current cover letter again before rewriting.")
    decisions = session.cover_letter_decisions.get(payload.draft_id, {})
    item = next((value for value in session.current_cover_letter.claims if value.item_id == payload.item_id), None)
    if item is None:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_cover_letter_item", "This item is not available in the current cover letter.")
    if decisions.get(item.item_id, CoverLetterDecision.KEEP) is CoverLetterDecision.REMOVE:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "removed_cover_letter_item", "A removed cover letter item cannot be rewritten.")
    rewrite = enhance_cover_letter_wording(item_id=item.item_id, original_text=item.text, category=item.category)
    session_store.set_cover_letter_rewrite(payload.session_id, draft_id=payload.draft_id, item_id=item.item_id, rewrite=rewrite)
    return review_cover_letter(session.current_cover_letter, decisions, session.cover_letter_rewrites[payload.draft_id])


def _current_cover_letter_projection(session, draft_id: str):
    if session.current_cover_letter is None or session.current_cover_letter_id != draft_id:
        raise _api_error(status.HTTP_409_CONFLICT, "stale_draft", "Generate the current cover letter again before exporting.")
    reviewed = review_cover_letter(session.current_cover_letter, session.cover_letter_decisions.get(draft_id, {}), session.cover_letter_rewrites.get(draft_id, {}))
    return build_public_cover_letter_projection(profile=session.profile, reviewed=reviewed)


@router.post("/generate/cover-letter/export/docx")
def export_cover_letter_as_docx(payload: CoverLetterExportRequest) -> Response:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before exporting a cover letter.")
    projection = _current_cover_letter_projection(session, payload.draft_id)
    try:
        content = export_cover_letter_docx(projection)
    except CoverLetterDocxExportError as error:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "cover_letter_docx_export_failed", "The reviewed cover letter could not be exported safely.") from error
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": 'attachment; filename="Cover_Letter.docx"'})


@router.post("/generate/cover-letter/export/pdf")
def export_cover_letter_as_pdf(payload: CoverLetterExportRequest) -> Response:
    session = session_store.get(payload.session_id)
    if session is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before exporting a cover letter.")
    projection = _current_cover_letter_projection(session, payload.draft_id)
    try:
        content = export_cover_letter_pdf(projection)
    except CoverLetterPdfExportError as error:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "cover_letter_pdf_export_failed", "The reviewed cover letter could not be exported safely.") from error
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="Cover_Letter.pdf"'})

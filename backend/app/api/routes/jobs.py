from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.routes.cv import _scrub_public_payload, session_store
from app.domain.job import JobDocument
from app.services.analysis_session.schemas import JobAnalysisRequest
from app.services.job_analysis import analyze_job_description
from app.services.job_coach import generate_job_specific_coach_questions
from app.services.job_match import match_job_to_profile
from app.services.job_match_score import calculate_job_match_score

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobAnalysisResponse(BaseModel):
    """Public job projection; evidence and job-source references stay server-side."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_analysis: dict[str, Any]
    job_match: dict[str, Any]
    job_score: dict[str, Any]
    job_coach: dict[str, Any]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _public_match(match) -> dict:
    """Keep evidence lineage server-side; browser clients need the evaluated outcome only."""
    return _scrub_public_payload(match.model_dump(mode="json"))


@router.post("/analyze", response_model=JobAnalysisResponse)
def analyze_job(payload: JobAnalysisRequest) -> JobAnalysisResponse:
    """Analyze pasted job text and match it only against the stored CV profile."""
    session = session_store.get(payload.session_id)
    if session is None:
        raise _error(status.HTTP_404_NOT_FOUND, "analysis_session_not_found", "Analyze a CV before analyzing a job listing.")
    if not payload.job_text.strip():
        raise _error(status.HTTP_400_BAD_REQUEST, "empty_job_text", "Job listing text is required.")
    try:
        analysis = analyze_job_description(JobDocument(
            raw_text=payload.job_text,
            title_hint=payload.title_hint,
            company_hint=payload.company_hint,
            source_reference="user:pasted-job",
        ))
        match = match_job_to_profile(analysis.profile, session.profile, analysis.unresolved_items)
        score = calculate_job_match_score(match)
        coach = generate_job_specific_coach_questions(analysis.profile, match)
    except (TypeError, ValueError) as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "job_analysis_failed", "The job listing could not be analyzed safely.") from error
    session_store.set_job_results(payload.session_id, job_analysis=analysis, job_match=match, job_score=score, job_coach=coach)
    return JobAnalysisResponse(
        job_analysis=_scrub_public_payload(analysis.model_dump(mode="json")),
        job_match=_public_match(match),
        job_score=_scrub_public_payload(score.model_dump(mode="json")),
        job_coach=_scrub_public_payload(coach.model_dump(mode="json")),
    )

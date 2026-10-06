"""Small replaceable in-memory context for the development analysis flow."""

from dataclasses import dataclass, field
import hashlib
from threading import RLock
from uuid import uuid4

from app.core.config import get_settings

from app.domain.career import CareerProfile
from app.services.career_gap_analysis import CoachQuestion, GapAnalysisResult
from app.services.cv_quality_analysis import CVQualityResult
from app.services.career_context import UnifiedCareerContext
from app.services.job_analysis import JobAnalysisResult
from app.services.job_coach import JobCoachResult
from app.services.job_match import JobMatchResult
from app.services.job_match_score import JobMatchScoreResult
from app.services.generation_orchestration import GeneratedCvDraft
from app.services.draft_review import DraftDecision
from app.services.cover_letter import CoverLetterDecision, CoverLetterDraft
from app.services.cover_letter.rewrite import CoverLetterRewriteResult
from app.ai.career import CareerFactCandidate
from app.confirmation.structured import WorkExperienceCandidate
from app.confirmation.structured.schemas import WorkExperienceResolutionResult
from app.domain.document.continuation import CompanyContinuationEvidence
from app.extraction.career import UnresolvedEvidence
from app.services.analysis_session.persistence import PersistedAnalysisSessionV1, SQLiteSessionPersistence
from app.services.career_context import build_analyzed_unified_career_context
from app.services.career_gap_analysis import analyze_career_profile_gaps
from app.services.cv_quality_analysis.service import analyze_cv_quality
from app.services.job_match import match_job_to_profile
from app.services.job_match_score import calculate_job_match_score
from app.services.job_coach import generate_job_specific_coach_questions


def readiness_evidence_id(evidence: UnresolvedEvidence) -> str:
    """Public-safe, stable capability for one retained unresolved source item."""

    value = "|".join((evidence.block_reference, evidence.section_type.value if evidence.section_type else "", evidence.reason))
    return f"readiness:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def active_unresolved_evidence(session: "AnalysisSession") -> tuple[UnresolvedEvidence, ...]:
    return tuple(item for item in session.unresolved_evidence if readiness_evidence_id(item) not in session.readiness_rejected_evidence_ids)


@dataclass(frozen=True)
class ContinuationCandidateState:
    """Server-owned exact pairing; neither side is a trusted company claim."""

    work_candidate: WorkExperienceCandidate
    evidence: CompanyContinuationEvidence


@dataclass
class AnalysisSession:
    profile: CareerProfile
    quality: CVQualityResult
    coach: GapAnalysisResult
    questions: dict[str, CoachQuestion]
    unified_career_context: UnifiedCareerContext | None = None
    context_revision: int = 0
    job_analysis: JobAnalysisResult | None = None
    job_match: JobMatchResult | None = None
    job_score: JobMatchScoreResult | None = None
    job_coach: JobCoachResult | None = None
    job_context_revision: int | None = None
    current_generated_draft: GeneratedCvDraft | None = None
    current_draft_id: str | None = None
    draft_decisions: dict[str, dict[str, DraftDecision]] = field(default_factory=dict)
    draft_rewrites: dict[str, dict[str, str]] = field(default_factory=dict)
    current_cover_letter: CoverLetterDraft | None = None
    current_cover_letter_id: str | None = None
    cover_letter_decisions: dict[str, dict[str, CoverLetterDecision]] = field(default_factory=dict)
    cover_letter_rewrites: dict[str, dict[str, CoverLetterRewriteResult]] = field(default_factory=dict)
    coach_candidates: dict[str, CareerFactCandidate] = field(default_factory=dict)
    coach_resolution_status: dict[str, str] = field(default_factory=dict)
    resolved_candidate_ids: set[str] = field(default_factory=set)
    continuation_candidates: dict[str, ContinuationCandidateState] = field(default_factory=dict)
    continuation_resolutions: dict[str, WorkExperienceResolutionResult] = field(default_factory=dict)
    unresolved_evidence: tuple[UnresolvedEvidence, ...] = ()
    readiness_rejected_evidence_ids: set[str] = field(default_factory=set)


@dataclass
class AnalysisSessionStore:
    """Storage boundary that can be replaced by a database-backed repository later."""

    _sessions: dict[str, AnalysisSession] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)
    persistence: SQLiteSessionPersistence | None = None

    def __post_init__(self) -> None:
        if self.persistence is None:
            settings = get_settings()
            self.persistence = SQLiteSessionPersistence(settings.session_db_path, ttl_hours=settings.session_ttl_hours)

    def _snapshot(self, session: AnalysisSession) -> PersistedAnalysisSessionV1:
        return PersistedAnalysisSessionV1(
            context_revision=session.context_revision,
            profile=session.profile.model_dump(mode="json"),
            quality=session.quality.model_dump(mode="json"),
            unresolved_evidence=[item.model_dump(mode="json") for item in session.unresolved_evidence],
            readiness_rejected_evidence_ids=sorted(session.readiness_rejected_evidence_ids),
            coach_candidates={key: value.model_dump(mode="json") for key, value in session.coach_candidates.items()},
            coach_resolution_status=dict(session.coach_resolution_status),
            resolved_candidate_ids=sorted(session.resolved_candidate_ids),
            continuation_candidates={key: {"work_candidate": value.work_candidate.model_dump(mode="json"), "evidence": value.evidence.model_dump(mode="json")} for key, value in session.continuation_candidates.items()},
            continuation_resolutions={key: value.model_dump(mode="json") for key, value in session.continuation_resolutions.items()},
            job_analysis=session.job_analysis.model_dump(mode="json") if session.job_analysis is not None else None,
        )

    def _persist(self, session_id: str, session: AnalysisSession) -> None:
        assert self.persistence is not None
        self.persistence.save(session_id, self._snapshot(session))

    def persist_session(self, session_id: str) -> None:
        """Persist a canonical/user-confirmed route-level mutation."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                self._persist(session_id, session)

    def delete(self, session_id: str) -> None:
        """Delete durable state before dropping the in-process object.

        The operation is deliberately idempotent: a bearer of an opaque ID
        cannot use this endpoint to distinguish unknown from expired/deleted
        sessions.
        """
        with self._lock:
            assert self.persistence is not None
            self.persistence.delete(session_id)
            self._sessions.pop(session_id, None)

    def _restore(self, snapshot: PersistedAnalysisSessionV1) -> AnalysisSession:
        from app.ai.career import CareerFactCandidate
        from app.confirmation.structured import WorkExperienceCandidate
        from app.confirmation.structured.schemas import WorkExperienceResolutionResult
        from app.domain.document.continuation import CompanyContinuationEvidence

        profile = CareerProfile.model_validate(snapshot.profile)
        unresolved = tuple(UnresolvedEvidence.model_validate(item) for item in snapshot.unresolved_evidence)
        continuations = {
            key: ContinuationCandidateState(
                work_candidate=WorkExperienceCandidate.model_validate(value["work_candidate"]),
                evidence=CompanyContinuationEvidence.model_validate(value["evidence"]),
            )
            for key, value in snapshot.continuation_candidates.items()
        }
        resolutions = {key: WorkExperienceResolutionResult.model_validate(value) for key, value in snapshot.continuation_resolutions.items()}
        rejected_ids = set(snapshot.readiness_rejected_evidence_ids)
        active_unresolved = tuple(item for item in unresolved if readiness_evidence_id(item) not in rejected_ids)
        context = build_analyzed_unified_career_context(profile=profile, unresolved_evidence=active_unresolved, work_results=tuple(resolutions.values()))
        coach = analyze_career_profile_gaps(profile)
        session = AnalysisSession(
            profile=profile,
            quality=(
                CVQualityResult.model_validate(snapshot.quality)
                if snapshot.quality is not None
                else analyze_cv_quality(profile, document=None, unresolved_evidence=unresolved)
            ),
            coach=coach,
            questions={item.question_id: item for item in coach.questions},
            unified_career_context=context,
            context_revision=snapshot.context_revision,
            coach_candidates={key: CareerFactCandidate.model_validate(value) for key, value in snapshot.coach_candidates.items()},
            coach_resolution_status=dict(snapshot.coach_resolution_status),
            resolved_candidate_ids=set(snapshot.resolved_candidate_ids),
            continuation_candidates=continuations,
            continuation_resolutions=resolutions,
            unresolved_evidence=unresolved,
            readiness_rejected_evidence_ids=rejected_ids,
        )
        if snapshot.job_analysis is not None:
            analysis = JobAnalysisResult.model_validate(snapshot.job_analysis)
            match = match_job_to_profile(analysis.profile, profile, analysis.unresolved_items)
            score = calculate_job_match_score(match)
            job_coach = generate_job_specific_coach_questions(analysis.profile, match)
            session.job_analysis, session.job_match, session.job_score, session.job_coach = analysis, match, score, job_coach
            session.job_context_revision = session.context_revision
            session.questions.update({item.question.question_id: item.question for item in job_coach.questions})
        return session

    def create(self, session: AnalysisSession) -> str:
        session_id = uuid4().hex
        with self._lock:
            self._sessions[session_id] = session
            self._persist(session_id, session)
        return session_id

    def get(self, session_id: str) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                return session
            assert self.persistence is not None
            snapshot = self.persistence.load(session_id)
            if snapshot is None:
                return None
            try:
                session = self._restore(snapshot)
            except (TypeError, ValueError, KeyError):
                self.persistence.delete(session_id)
                return None
            self._sessions[session_id] = session
            return session

    def get_unified_career_context(self, session_id: str) -> UnifiedCareerContext | None:
        """Return only the immutable server-produced aggregate for a session."""

        with self._lock:
            session = self._sessions.get(session_id)
            return session.unified_career_context if session is not None else None

    def set_unified_career_context(
        self,
        session_id: str,
        *,
        context: UnifiedCareerContext,
        preserve_job_analysis: bool = False,
    ) -> AnalysisSession | None:
        """Replace context and invalidate profile-derived state.

        Job analysis is a parse of user-supplied job text, so it can be
        retained when only the canonical CV profile changed. Its match, score
        and coach output remain profile-derived and are always cleared.
        """

        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.unified_career_context = context
            session.context_revision += 1
            if not preserve_job_analysis:
                session.job_analysis = None
            session.job_match = None
            session.job_score = None
            session.job_coach = None
            session.job_context_revision = None
            session.current_generated_draft = None
            session.current_draft_id = None
            session.current_cover_letter = None
            session.current_cover_letter_id = None
            self._persist(session_id, session)
            return session

    def invalidate_unified_career_context(self, session_id: str) -> AnalysisSession | None:
        """Prevent a pre-answer context from being reused after coach input."""

        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.unified_career_context = None
            session.context_revision += 1
            session.job_analysis = None
            session.job_match = None
            session.job_score = None
            session.job_coach = None
            session.job_context_revision = None
            session.current_generated_draft = None
            session.current_draft_id = None
            session.current_cover_letter = None
            session.current_cover_letter_id = None
            self._persist(session_id, session)
            return session

    def set_coach_candidate(self, session_id: str, *, candidate_id: str, candidate: CareerFactCandidate) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.coach_candidates[candidate_id] = candidate
                self._persist(session_id, session)
            return session

    def set_continuation_candidates(self, session_id: str, *, candidates: tuple[ContinuationCandidateState, ...]) -> AnalysisSession | None:
        """Replace analysis-produced continuation state; callers cannot supply it via API."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            ids = [item.evidence.candidate_id for item in candidates]
            if len(ids) != len(set(ids)):
                raise ValueError("Continuation evidence IDs must be unique within a session.")
            session.continuation_candidates = {item.evidence.candidate_id: item for item in candidates}
            session.continuation_resolutions = {}
            self._persist(session_id, session)
            return session

    def reject_readiness_evidence(self, session_id: str, *, finding_id: str) -> AnalysisSession | None:
        """Omit only one server-owned unresolved source item from generation readiness."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or finding_id in session.readiness_rejected_evidence_ids:
                return None
            if not any(readiness_evidence_id(item) == finding_id for item in session.unresolved_evidence):
                return None
            session.readiness_rejected_evidence_ids.add(finding_id)
            self._persist(session_id, session)
            return session

    def resolve_continuation_candidate(self, session_id: str, *, candidate_id: str, result: WorkExperienceResolutionResult) -> AnalysisSession | None:
        """Consume one exact server-owned proposal; a resolved ID is never reusable."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or candidate_id not in session.continuation_candidates or candidate_id in session.continuation_resolutions:
                return None
            session.continuation_resolutions[candidate_id] = result
            self._persist(session_id, session)
            return session

    def set_generated_draft(self, session_id: str, *, draft: GeneratedCvDraft, draft_id: str) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.current_generated_draft = draft
            session.current_draft_id = draft_id
            return session

    def set_cover_letter(self, session_id: str, *, draft: CoverLetterDraft) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.current_cover_letter = draft
            session.current_cover_letter_id = draft.draft_id
            session.cover_letter_decisions.pop(draft.draft_id, None)
            session.cover_letter_rewrites.pop(draft.draft_id, None)
            return session

    def set_cover_letter_decision(self, session_id: str, *, draft_id: str, item_id: str, decision: CoverLetterDecision) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.current_cover_letter_id != draft_id or session.current_cover_letter is None:
                return None
            session.cover_letter_decisions.setdefault(draft_id, {})[item_id] = decision
            return session

    def set_cover_letter_rewrite(self, session_id: str, *, draft_id: str, item_id: str, rewrite: CoverLetterRewriteResult) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.current_cover_letter_id != draft_id or session.current_cover_letter is None:
                return None
            session.cover_letter_rewrites.setdefault(draft_id, {})[item_id] = rewrite
            return session

    def set_draft_decision(self, session_id: str, *, draft_id: str, item_id: str, decision: DraftDecision) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.current_draft_id != draft_id or session.current_generated_draft is None:
                return None
            session.draft_decisions.setdefault(draft_id, {})[item_id] = decision
            return session

    def set_draft_rewrite(self, session_id: str, *, draft_id: str, item_id: str, text: str) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.current_draft_id != draft_id:
                return None
            session.draft_rewrites.setdefault(draft_id, {})[item_id] = text
            return session

    def has_current_job_match(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            return bool(
                session is not None
                and session.unified_career_context is not None
                and session.job_match is not None
                and session.job_context_revision == session.context_revision
            )

    def set_job_results(
        self,
        session_id: str,
        *,
        job_analysis: JobAnalysisResult,
        job_match: JobMatchResult,
        job_score: JobMatchScoreResult,
        job_coach: JobCoachResult,
    ) -> AnalysisSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.job_analysis = job_analysis
            session.job_match = job_match
            session.job_score = job_score
            session.job_coach = job_coach
            session.job_context_revision = session.context_revision
            # A new job changes targeted evidence selection.  Keep a general
            # draft, but never let an old targeted draft survive server-side.
            if session.current_generated_draft is not None and session.current_generated_draft.mode.value == "targeted":
                session.current_generated_draft = None
                session.current_draft_id = None
            session.current_cover_letter = None
            session.current_cover_letter_id = None
            session.questions.update({item.question.question_id: item.question for item in job_coach.questions})
            self._persist(session_id, session)
            return session

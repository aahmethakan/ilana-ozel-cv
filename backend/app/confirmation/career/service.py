import hashlib
import json

from app.ai.career.schemas import CandidateType
from app.ai.career.validation import CareerFactCandidate
from app.confirmation.career.schemas import (
    CandidateResolutionResult,
    ConfirmationAction,
    ResolutionAudit,
    ResolutionStatus,
)
from app.domain.career import CareerFact, FactSource, SourceType, VerificationStatus

_PROMOTABLE_TYPES = {
    CandidateType.SKILL,
    CandidateType.LANGUAGE,
    CandidateType.CERTIFICATION,
    CandidateType.PROJECT,
    CandidateType.PUBLICATION,
}
_BLOCKING_ISSUES = {
    "unsupported_strengthening",
    "unsupported_metric",
    "unsupported_responsibility",
    "unsupported_leadership",
    "unknown_evidence_reference",
    "missing_evidence",
    "structurally_invalid_proposal",
}


def candidate_id(candidate: CareerFactCandidate) -> str:
    """Stable content identity for an in-memory audit trail."""

    payload = json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _audit(candidate: CareerFactCandidate, action: ConfirmationAction, correction: str | None = None, fact: CareerFact | None = None) -> ResolutionAudit:
    return ResolutionAudit(
        candidate_id=candidate_id(candidate),
        action=action,
        original_proposed_statement=candidate.proposed_statement,
        evidence_references=candidate.evidence_references,
        user_correction=correction,
        resulting_fact_statement=fact.statement if fact else None,
    )


def _user_fact(candidate: CareerFactCandidate, statement: str, action: ConfirmationAction) -> CareerFact:
    identifier = candidate_id(candidate)
    return CareerFact(
        statement=statement,
        verification_status=VerificationStatus.USER_PROVIDED,
        source=FactSource(
            source_type=SourceType.USER_INPUT,
            reference=f"candidate:{identifier}:{action.value}",
            original_text=statement,
        ),
        skills=(statement,) if candidate.candidate_type is CandidateType.SKILL else (),
    )


def resolve_candidate(
    candidate: CareerFactCandidate,
    action: ConfirmationAction,
    *,
    correction: str | None = None,
    resolved_candidate_ids: frozenset[str] = frozenset(),
) -> CandidateResolutionResult:
    """Resolve one immutable AI candidate; only explicit user action can create a usable fact."""

    identifier = candidate_id(candidate)
    if identifier in resolved_candidate_ids:
        return CandidateResolutionResult(candidate=candidate, status=ResolutionStatus.BLOCKED, audit=_audit(candidate, action), issue_codes=("already_resolved",))
    if action is ConfirmationAction.REJECT:
        return CandidateResolutionResult(candidate=candidate, status=ResolutionStatus.REJECTED, audit=_audit(candidate, action))
    if action is ConfirmationAction.CORRECT:
        value = (correction or "").strip()
        if not value:
            return CandidateResolutionResult(candidate=candidate, status=ResolutionStatus.BLOCKED, audit=_audit(candidate, action), issue_codes=("missing_user_correction",))
        fact = _user_fact(candidate, value, action)
        return CandidateResolutionResult(candidate=candidate, status=ResolutionStatus.PROMOTED, audit=_audit(candidate, action, value, fact), promoted_fact=fact)
    blocking = tuple(issue for issue in candidate.issue_codes if issue in _BLOCKING_ISSUES)
    if blocking:
        return CandidateResolutionResult(candidate=candidate, status=ResolutionStatus.BLOCKED, audit=_audit(candidate, action), issue_codes=blocking)
    if candidate.candidate_type not in _PROMOTABLE_TYPES:
        return CandidateResolutionResult(candidate=candidate, status=ResolutionStatus.BLOCKED, audit=_audit(candidate, action), issue_codes=("unsupported_candidate_type",))
    fact = _user_fact(candidate, candidate.proposed_statement, action)
    return CandidateResolutionResult(candidate=candidate, status=ResolutionStatus.PROMOTED, audit=_audit(candidate, action, fact=fact), promoted_fact=fact)

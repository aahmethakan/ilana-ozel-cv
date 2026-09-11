from pydantic import BaseModel, ConfigDict, Field

from app.ai.career.validation import CareerFactCandidate, RejectedAIProposal
from app.domain.career import CareerProfile
from app.extraction.career.result import UnresolvedEvidence


class ProcessingIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_reference: str
    issue_code: str
    safe_message: str


class CareerAssistanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deterministic_profile: CareerProfile
    deterministic_unresolved_evidence: tuple[UnresolvedEvidence, ...]
    ai_candidates: tuple[CareerFactCandidate, ...] = Field(default_factory=tuple)
    rejected_ai_proposals: tuple[RejectedAIProposal, ...] = Field(default_factory=tuple)
    remaining_unresolved_evidence: tuple[UnresolvedEvidence, ...] = Field(default_factory=tuple)
    processing_issues: tuple[ProcessingIssue, ...] = Field(default_factory=tuple)

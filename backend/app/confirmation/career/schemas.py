from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.ai.career.validation import CareerFactCandidate
from app.domain.career import CareerFact


class ConfirmationAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    CORRECT = "correct"


class ResolutionStatus(StrEnum):
    PROMOTED = "promoted"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class ResolutionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    action: ConfirmationAction
    original_proposed_statement: str
    evidence_references: tuple[str, ...] = Field(min_length=1)
    user_correction: str | None = None
    resulting_fact_statement: str | None = None


class CandidateResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: CareerFactCandidate
    status: ResolutionStatus
    audit: ResolutionAudit
    promoted_fact: CareerFact | None = None
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def is_rejected(self) -> bool:
        return self.status is ResolutionStatus.REJECTED

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.ai.career.validation import CareerFactCandidate
from app.domain.career import FactSource


class CoachAnswerStatus(StrEnum):
    CANDIDATE_CREATED = "candidate_created"
    REJECTED = "rejected"
    ANSWERED_NO = "answered_no"
    DEFERRED = "deferred"


class CoachAnswer(BaseModel):
    """Explicit user text answering one previously generated coach question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str
    answer_text: str


class CoachAnswerProcessingResult(BaseModel):
    """Untrusted candidate output with user-answer provenance retained outside the candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_question_id: str
    status: CoachAnswerStatus
    candidate: CareerFactCandidate | None = None
    source: FactSource | None = None
    normalized_answer: str | None = None
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)

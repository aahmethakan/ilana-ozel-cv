from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.generation_strategy import GenerationMode
from app.services.draft_review import DraftDecision
from app.confirmation.career import ConfirmationAction


class CoachAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    answer_text: str = Field(min_length=1, max_length=4_000)


class SessionRecoveryRequest(BaseModel):
    """Opaque capability sent in a JSON body so it is not placed in URLs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)


class SessionDeletionRequest(BaseModel):
    """Opaque capability sent in a JSON body; deletion is intentionally idempotent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)


class ReadinessResolutionRequest(BaseModel):
    """A narrow request to omit one server-issued unresolved source item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    action: str

    @model_validator(mode="after")
    def only_supports_safe_omission(self) -> "ReadinessResolutionRequest":
        if self.action != "reject":
            raise ValueError("This readiness item can only be rejected.")
        return self


class CoachCandidateResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    action: ConfirmationAction
    correction: str | None = Field(default=None, max_length=1_000)


class ContinuationResolutionAction(StrEnum):
    ACCEPT = "ACCEPT"
    CORRECT = "CORRECT"
    REJECT = "REJECT"
    LEAVE_UNRESOLVED = "LEAVE_UNRESOLVED"


class ContinuationCandidateResolutionRequest(BaseModel):
    """Only the opaque server-issued continuation proposal may be resolved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    action: ContinuationResolutionAction
    correction: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "ContinuationCandidateResolutionRequest":
        if self.action is ContinuationResolutionAction.CORRECT:
            if self.correction is None or not self.correction.strip():
                raise ValueError("CORRECT requires a non-empty correction.")
        elif self.correction is not None:
            raise ValueError(f"{self.action.value} does not accept a correction.")
        return self


class JobAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    job_text: str = Field(min_length=1, max_length=100_000)
    title_hint: str | None = Field(default=None, max_length=200)
    company_hint: str | None = Field(default=None, max_length=200)


class GenerationReviewRequest(BaseModel):
    """Operational input only; all generation evidence remains server-side."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    mode: GenerationMode


class GenerationReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    decision: DraftDecision


class GenerationRewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)


class DocxExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)


class PdfExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)


class CvValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)


class CvQualityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)


class CoverLetterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    mode: GenerationMode


class CoverLetterDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    decision: DraftDecision


class CoverLetterRewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)


class CoverLetterExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)

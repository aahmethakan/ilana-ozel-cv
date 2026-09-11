import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.ai.career.schemas import AIConfidence, AIProposedCandidate, CandidateField, CandidateType
from app.domain.career import VerificationStatus

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CareerFactCandidate(BaseModel):
    """An AI proposal retained for review, explicitly separate from CareerFact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_type: CandidateType
    proposed_statement: NonEmptyText
    proposed_fields: tuple[CandidateField, ...] = Field(default_factory=tuple)
    evidence_references: tuple[NonEmptyText, ...] = Field(min_length=1)
    confidence: AIConfidence
    verification_status: Literal[VerificationStatus.INFERRED_UNVERIFIED] = (
        VerificationStatus.INFERRED_UNVERIFIED
    )
    requires_user_confirmation: Literal[True] = True
    rationale: NonEmptyText | None = None
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def is_claim_usable(self) -> bool:
        return False


class RejectedAIProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposed_statement: str
    reason: str


class CareerCandidateValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[CareerFactCandidate, ...] = Field(default_factory=tuple)
    rejected_proposals: tuple[RejectedAIProposal, ...] = Field(default_factory=tuple)


class InflationValidator:
    """Extensible deterministic checks for common unsupported strengthening patterns."""

    _METRIC_PATTERN = re.compile(r"\b\d+(?:[.,]\d+)?\s*%")
    _LEADERSHIP_PATTERN = re.compile(r"\b(?:led|lead|managed|supervised|leadership)\b", re.I)

    def issue_codes(self, proposal: AIProposedCandidate, source_text: str) -> tuple[str, ...]:
        proposed = proposal.proposed_statement.casefold()
        source = source_text.casefold()
        issues: list[str] = []
        if self._METRIC_PATTERN.search(proposal.proposed_statement) and not self._METRIC_PATTERN.search(source_text):
            issues.append("unsupported_metric")
        if "sap erp" in proposed and "sap erp" not in source and re.search(r"\bsap\b", source):
            issues.append("unsupported_strengthening")
        if "advanced excel" in proposed and "advanced excel" not in source and re.search(r"\bexcel\b", source):
            issues.append("unsupported_strengthening")
        if "senior engineer" in proposed and "senior engineer" not in source and re.search(r"\bengineer\b", source):
            issues.append("unsupported_seniority")
        if self._LEADERSHIP_PATTERN.search(proposal.proposed_statement) and not self._LEADERSHIP_PATTERN.search(source_text):
            issues.append("unsupported_responsibility")
        return tuple(dict.fromkeys(issues))


def candidate_from_proposal(
    proposal: AIProposedCandidate, source_text: str, validator: InflationValidator | None = None
) -> CareerFactCandidate:
    """Create an always-unverified candidate after evidence references are validated."""

    checks = validator or InflationValidator()
    return CareerFactCandidate(
        candidate_type=proposal.candidate_type,
        proposed_statement=proposal.proposed_statement,
        proposed_fields=proposal.proposed_fields,
        evidence_references=proposal.evidence_references,
        confidence=proposal.confidence,
        rationale=proposal.rationale,
        issue_codes=checks.issue_codes(proposal, source_text),
    )


def can_auto_promote(candidate: CareerFactCandidate) -> bool:
    """V1 intentionally permits no automatic promotion from AI proposal to CareerFact."""

    _ = candidate
    return False

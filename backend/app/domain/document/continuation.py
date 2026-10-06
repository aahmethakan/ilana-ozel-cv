"""Unverified layout evidence for a company name omitted from a following role."""

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from app.domain.document.evidence import ParserConfidence


class CompanyContinuationEvidence(BaseModel):
    """Geometry may propose continuity; it never verifies a company claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    proposed_company: str = Field(min_length=1)
    previous_company_reference: str = Field(min_length=1)
    current_role_references: tuple[str, ...] = Field(min_length=1)
    section_reference: str = Field(min_length=1)
    confidence: ParserConfidence
    verification_status: str = "inferred_unverified"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "proposed_company": self.proposed_company,
            "previous_company_reference": self.previous_company_reference,
            "current_role_references": list(self.current_role_references),
            "section_reference": self.section_reference,
            "confidence": self.confidence.value,
        }


def company_continuation_candidate_id(*, proposed_company: str, previous_company_reference: str, current_role_references: tuple[str, ...], section_reference: str, confidence: ParserConfidence) -> str:
    payload = {
        "proposed_company": proposed_company,
        "previous_company_reference": previous_company_reference,
        "current_role_references": list(current_role_references),
        "section_reference": section_reference,
        "confidence": confidence.value,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"company-continuation:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def create_company_continuation_evidence(*, proposed_company: str, previous_company_reference: str, current_role_references: tuple[str, ...], section_reference: str, confidence: ParserConfidence) -> CompanyContinuationEvidence:
    return CompanyContinuationEvidence(
        candidate_id=company_continuation_candidate_id(proposed_company=proposed_company, previous_company_reference=previous_company_reference, current_role_references=current_role_references, section_reference=section_reference, confidence=confidence),
        proposed_company=proposed_company,
        previous_company_reference=previous_company_reference,
        current_role_references=current_role_references,
        section_reference=section_reference,
        confidence=confidence,
    )

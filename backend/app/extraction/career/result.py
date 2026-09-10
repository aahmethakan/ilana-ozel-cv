from pydantic import BaseModel, ConfigDict

from app.domain.career import CareerProfile
from app.domain.document import SectionType


class UnresolvedEvidence(BaseModel):
    """A meaningful source block deliberately not promoted to a career fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_reference: str
    section_type: SectionType | None = None
    reason: str


class CareerExtractionResult(BaseModel):
    """Safe structured extraction plus source evidence requiring later review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: CareerProfile
    unresolved_evidence: tuple[UnresolvedEvidence, ...] = ()

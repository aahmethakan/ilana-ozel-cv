from pydantic import BaseModel, ConfigDict, Field

from app.domain.career import CareerProfile, SourceType
from app.services.cover_letter import ReviewedCoverLetter


class PublicCoverLetterContact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    email: str | None = None
    phone: str | None = None
    website: str | None = None


class PublicCoverLetterProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_name: str | None = None
    contact: PublicCoverLetterContact = Field(default_factory=PublicCoverLetterContact)
    target_role: str | None = None
    target_company: str | None = None
    opening: str
    body_sections: tuple[str, ...] = Field(default_factory=tuple)
    closing: str


def build_public_cover_letter_projection(*, profile: CareerProfile, reviewed: ReviewedCoverLetter) -> PublicCoverLetterProjection:
    def direct(value):
        return value.value if value is not None and value.source.source_type in {SourceType.MASTER_CV, SourceType.USER_INPUT} else None
    contact = profile.contact
    return PublicCoverLetterProjection(
        candidate_name=profile.full_name,
        contact=PublicCoverLetterContact(email=direct(contact.email) if contact else None, phone=direct(contact.phone) if contact else None, website=direct(contact.website) if contact else None),
        target_role=reviewed.target_role,
        target_company=reviewed.target_company,
        opening=reviewed.opening,
        body_sections=reviewed.body_sections,
        closing=reviewed.closing,
    )

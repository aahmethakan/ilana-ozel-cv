from pydantic import BaseModel, ConfigDict, Field

from app.domain.career import CareerProfile, SourceType, is_verification_usable
from app.services.draft_review import ReviewedCvDraft


class PublicCvContact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    email: str | None = None
    phone: str | None = None
    website: str | None = None


class PublicCvProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str | None = None
    headline: str | None = None
    contact: PublicCvContact = Field(default_factory=PublicCvContact)
    summary: str | None = None
    reviewed_draft: ReviewedCvDraft


def build_public_cv_projection(*, profile: CareerProfile, reviewed_draft: ReviewedCvDraft) -> PublicCvProjection:
    def direct(value): return value.value if value is not None and is_verification_usable(value.verification_status) and value.source.source_type in {SourceType.MASTER_CV, SourceType.USER_INPUT} else None
    def identity_value(value, fallback):
        if value is None:
            return fallback
        return value.value if value.is_claim_usable and value.value_source.source_type in {SourceType.MASTER_CV, SourceType.USER_INPUT} else None
    contact = profile.contact
    summary = next((fact.statement for fact in profile.summary_facts if fact.is_claim_usable and fact.source.source_type in {SourceType.MASTER_CV, SourceType.USER_INPUT}), None)
    return PublicCvProjection(
        name=identity_value(profile.identity.name if profile.identity else None, profile.full_name),
        headline=identity_value(profile.identity.headline if profile.identity else None, profile.headline),
        contact=PublicCvContact(email=direct(contact.email) if contact else None, phone=direct(contact.phone) if contact else None, website=direct(contact.website) if contact else None),
        summary=summary,
        reviewed_draft=reviewed_draft,
    )

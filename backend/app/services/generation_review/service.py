from app.services.generation_orchestration import GeneratedCvDraft
from app.services.generation_review.schemas import DraftReviewClaim, DraftReviewEducationEntry, DraftReviewWorkEntry, GeneratedCvDraftReview


def build_generated_cv_review(draft: GeneratedCvDraft) -> GeneratedCvDraftReview:
    """Read-only projection; it never recreates generation inputs or claims."""
    skills = tuple(DraftReviewClaim(text=item.text, source="verified_evidence") for item in draft.skill_claims)
    entries = []
    for entry in draft.work_entries:
        identity = entry.identity_claim.text.split(" — ", 1)
        if len(identity) != 2 or entry.identity_claim.structured_lineage is None:
            raise ValueError("Draft work entry has incomplete public review lineage.")
        dates = entry.date_claim.text if entry.date_claim else None
        claims = tuple(DraftReviewClaim(text=item.text, source="verified_associated_evidence") for item in entry.fact_claims)
        entries.append(DraftReviewWorkEntry(company=identity[1], title=identity[0], dates=dates, claims=claims))
    education = []
    for entry in draft.education_entries:
        identity = entry.identity_claim.text.split(" â€” ", 1)
        qualification, institution = (identity[0], identity[1]) if len(identity) == 2 else (None, identity[0])
        education.append(DraftReviewEducationEntry(
            institution=institution,
            qualification=qualification,
            dates=entry.date_claim.text if entry.date_claim else None,
        ))
    return GeneratedCvDraftReview(mode=draft.mode, skills=skills, work_entries=tuple(entries), education=tuple(education))

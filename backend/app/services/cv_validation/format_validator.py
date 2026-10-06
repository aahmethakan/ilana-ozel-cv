from app.services.cv_validation.schemas import ValidationIssue, ValidationSeverity
from app.services.public_cv_projection import PublicCvProjection


def validate_format(projection: PublicCvProjection) -> tuple[ValidationIssue, ...]:
    review = projection.reviewed_draft.review
    values = [("SKILLS", item.text) for item in review.skills]
    values += [("WORK_EXPERIENCE", item.company) for item in review.work_entries]
    values += [("WORK_EXPERIENCE", item.title) for item in review.work_entries]
    values += [("WORK_EXPERIENCE", claim.text) for item in review.work_entries for claim in item.claims]
    values += [("EDUCATION", item.institution) for item in review.education]
    return tuple(ValidationIssue(validator="FORMAT", code="EMPTY_CONTENT", severity=ValidationSeverity.BLOCK, message="Bir CV bölümü boş içerik barındırıyor.", section=section) for section, value in values if not value or not value.strip())

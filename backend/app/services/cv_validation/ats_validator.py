from app.services.cv_validation.schemas import ValidationIssue, ValidationSeverity
from app.services.public_cv_projection import PublicCvProjection


def validate_ats(projection: PublicCvProjection) -> tuple[ValidationIssue, ...]:
    review = projection.reviewed_draft.review
    missing = (("NO_NAME", projection.name, "Ad bilgisi bulunamadı.", "HEADER"), ("NO_SKILLS", review.skills, "Beceri bölümü bulunamadı.", "SKILLS"), ("NO_WORK_EXPERIENCE", review.work_entries, "İş deneyimi bölümü bulunamadı.", "WORK_EXPERIENCE"), ("NO_EDUCATION", review.education, "Eğitim bölümü bulunamadı.", "EDUCATION"))
    return tuple(ValidationIssue(validator="ATS", code=code, severity=ValidationSeverity.WARNING, message=message, section=section) for code, value, message, section in missing if not value)

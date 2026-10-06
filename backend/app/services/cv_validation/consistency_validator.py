import re

from app.services.cv_validation.schemas import ValidationIssue, ValidationSeverity
from app.services.public_cv_projection import PublicCvProjection


def validate_consistency(projection: PublicCvProjection) -> tuple[ValidationIssue, ...]:
    review = projection.reviewed_draft.review
    issues: list[ValidationIssue] = []
    skill_texts = [item.text.casefold() for item in review.skills]
    if len(skill_texts) != len(set(skill_texts)):
        issues.append(_issue("DUPLICATE_SKILL", ValidationSeverity.WARNING, "Aynı beceri birden fazla kez yer alıyor.", "SKILLS"))
    work_keys = [(item.company.casefold(), item.title.casefold(), item.dates or "") for item in review.work_entries]
    if len(work_keys) != len(set(work_keys)):
        issues.append(_issue("DUPLICATE_WORK_ENTRY", ValidationSeverity.WARNING, "Aynı iş deneyimi birden fazla kez yer alıyor.", "WORK_EXPERIENCE"))
    education_keys = [(item.institution.casefold(), item.qualification or "", item.dates or "") for item in review.education]
    if len(education_keys) != len(set(education_keys)):
        issues.append(_issue("DUPLICATE_EDUCATION", ValidationSeverity.WARNING, "Aynı eğitim kaydı birden fazla kez yer alıyor.", "EDUCATION"))
    for entry in review.work_entries:
        if entry.dates and not re.search(r"\d{4}", entry.dates):
            issues.append(_issue("MALFORMED_DATE", ValidationSeverity.BLOCK, "Bir iş deneyimi tarihi geçerli görünmüyor.", "WORK_EXPERIENCE"))
    for value, code, label in ((projection.contact.email, "MALFORMED_EMAIL", "e-posta"), (projection.contact.phone, "MALFORMED_PHONE", "telefon"), (projection.contact.website, "MALFORMED_WEBSITE", "web adresi")):
        if value and ((code == "MALFORMED_EMAIL" and "@" not in value) or (code == "MALFORMED_PHONE" and len(re.sub(r"\D", "", value)) < 7) or (code == "MALFORMED_WEBSITE" and "." not in value)):
            issues.append(_issue(code, ValidationSeverity.BLOCK, f"Bir {label} bilgisi geçerli görünmüyor.", "CONTACT"))
    return tuple(issues)


def _issue(code: str, severity: ValidationSeverity, message: str, section: str) -> ValidationIssue:
    return ValidationIssue(validator="CONSISTENCY", code=code, severity=severity, message=message, section=section)

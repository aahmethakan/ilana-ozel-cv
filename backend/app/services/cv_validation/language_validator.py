import re

from app.services.cv_validation.schemas import ValidationIssue, ValidationSeverity
from app.services.public_cv_projection import PublicCvProjection


def validate_language(projection: PublicCvProjection) -> tuple[ValidationIssue, ...]:
    review = projection.reviewed_draft.review
    texts = [value for value in (projection.name, projection.headline, projection.summary) if value]
    texts += [item.text for item in review.skills]
    texts += [claim.text for entry in review.work_entries for claim in entry.claims]
    issues: list[ValidationIssue] = []
    for text in texts:
        if "�" in text:
            issues.append(_warning("SUSPICIOUS_ENCODING", "Metinde şüpheli karakter kodlaması bulunuyor."))
        if re.search(r"\b(\w+)\s+\1\b", text, re.I):
            issues.append(_warning("REPEATED_WORD", "Metinde yinelenen bir kelime bulunuyor."))
        if re.search(r"[!?.,]{3,}", text) or "  " in text:
            issues.append(_warning("BROKEN_WHITESPACE_OR_PUNCTUATION", "Metinde biçimsel bir dil sorunu bulunuyor."))
    return tuple(issues)


def _warning(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(validator="LANGUAGE", code=code, severity=ValidationSeverity.WARNING, message=message, section="CV")

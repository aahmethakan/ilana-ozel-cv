import hashlib
import re
import unicodedata
from collections import defaultdict

from app.domain.job import (
    JobDocument,
    JobProfile,
    JobRequirement,
    RequirementCategory,
    RequirementExplicitness,
    RequirementImportance,
)
from app.services.job_analysis.schemas import (
    JobAnalysisResult,
    JobImportanceConflict,
    JobMetadataConflict,
    UnresolvedJobItem,
)

_HEADING_CONTEXT = {
    "responsibilities": "responsibility", "duties": "responsibility", "what you'll do": "responsibility",
    "sorumluluklar": "responsibility", "görevler": "responsibility",
    "requirements": "required", "qualifications": "required", "must have": "required", "required qualifications": "required",
    "aranan nitelikler": "required", "gereksinimler": "required", "yetkinlikler": "required",
    "preferred qualifications": "preferred", "preferred": "preferred", "nice to have": "preferred",
    "tercih edilen": "preferred", "tercih sebebi": "preferred",
    "skills": "skills", "tools": "tools", "technologies": "tools",
    "education": "education", "eğitim": "education", "experience": "experience", "deneyim": "experience",
    "languages": "language", "language": "language", "yabancı dil": "language",
    "certifications": "certification", "sertifikalar": "certification",
    "about the role": "unknown",
    "who you are": "unknown",
}
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•–—]|\d+[.)])\s*")
_EXPERIENCE = re.compile(r"\b(?:\d+\+?\s+years?|minimum\s+\d+\s+years?|at\s+least\s+\d+\s+years?)\b", re.I)
_INLINE_REQUIRED = re.compile(r"\b(?:must|required|mandatory|minimum)\b", re.I)
_INLINE_PREFERRED = re.compile(r"\b(?:preferred|nice to have|desirable|advantage)\b", re.I)
_EDUCATION = re.compile(r"\b(?:bachelor'?s|master'?s|degree|lisans|yüksek lisans)\b", re.I)
_LANGUAGE = re.compile(r"\b(?:english|ingilizce|german|almanca|french|fransızca)\b", re.I)
_TITLE_LABEL = re.compile(r"^(?:job title|title|position)\s*:\s*(.+)$", re.I)
_COMPANY_LABEL = re.compile(r"^(?:company|employer)\s*:\s*(.+)$", re.I)


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _heading(line: str) -> str | None:
    return _HEADING_CONTEXT.get(_normalized(line).rstrip(":"))


def _importance(context: str | None, text: str) -> tuple[RequirementImportance, tuple[RequirementImportance, ...]]:
    observed: set[RequirementImportance] = set()
    if context == "required":
        observed.add(RequirementImportance.REQUIRED)
    elif context == "preferred":
        observed.add(RequirementImportance.PREFERRED)
    if _INLINE_REQUIRED.search(text):
        observed.add(RequirementImportance.REQUIRED)
    if _INLINE_PREFERRED.search(text):
        observed.add(RequirementImportance.PREFERRED)
    values = tuple(sorted(observed, key=lambda value: value.value))
    if len(values) != 1:
        return RequirementImportance.UNKNOWN, values
    return values[0], values


def _requirement_id(category: RequirementCategory, text: str) -> str:
    value = f"{category.value}|{_normalized(text)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _make_requirement(category: RequirementCategory, text: str, importance: RequirementImportance, reference: str, source_text: str) -> JobRequirement:
    return JobRequirement(
        requirement_id=_requirement_id(category, text),
        category=category,
        text=text,
        importance=importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source_references=(reference,),
        source_texts=(source_text,),
    )


def _category(context: str | None, text: str) -> RequirementCategory | None:
    if context == "skills":
        return RequirementCategory.SKILL
    if context == "tools":
        return RequirementCategory.TOOL
    if context == "education" or _EDUCATION.search(text):
        return RequirementCategory.EDUCATION
    if context == "experience" or _EXPERIENCE.search(text):
        return RequirementCategory.EXPERIENCE
    if context == "language" or _LANGUAGE.search(text):
        return RequirementCategory.LANGUAGE
    if context == "certification":
        return RequirementCategory.CERTIFICATION
    if context in {"required", "preferred"}:
        return RequirementCategory.OTHER
    return None


def _merge_exact(requirements: list[JobRequirement]) -> tuple[tuple[JobRequirement, ...], tuple[JobImportanceConflict, ...]]:
    grouped: dict[tuple[RequirementCategory, str], list[JobRequirement]] = defaultdict(list)
    for item in requirements:
        grouped[(item.category, _normalized(item.text))].append(item)

    merged: list[JobRequirement] = []
    conflicts: list[JobImportanceConflict] = []
    for (category, _), items in grouped.items():
        values = tuple(sorted({item.importance for item in items}, key=lambda value: value.value))
        merged.append(items[0].model_copy(update={
            "importance": values[0] if len(values) == 1 else RequirementImportance.UNKNOWN,
            "source_references": tuple(dict.fromkeys(reference for item in items for reference in item.source_references)),
            "source_texts": tuple(dict.fromkeys(source_text for item in items for source_text in item.source_texts)),
        }))
        if len(values) > 1:
            conflicts.append(JobImportanceConflict(
                category=category.value,
                text=items[0].text,
                importance_values=values,
                source_references=tuple(reference for item in items for reference in item.source_references),
                required_source_references=tuple(reference for item in items if item.importance is RequirementImportance.REQUIRED for reference in item.source_references),
                preferred_source_references=tuple(reference for item in items if item.importance is RequirementImportance.PREFERRED for reference in item.source_references),
            ))
    return tuple(sorted(merged, key=lambda item: item.requirement_id)), tuple(sorted(conflicts, key=lambda item: (item.category, item.text)))


def analyze_job_description(document: JobDocument) -> JobAnalysisResult:
    """Conservatively model pasted job text without AI or candidate matching."""

    context: str | None = None
    title = document.title_hint
    company = document.company_hint
    requirements: list[JobRequirement] = []
    responsibilities: list[JobRequirement] = []
    unresolved: list[UnresolvedJobItem] = []
    importance_conflicts: list[JobImportanceConflict] = []
    metadata_conflicts: list[JobMetadataConflict] = []
    for number, raw_line in enumerate(document.raw_text.splitlines(), start=1):
        reference = f"job:line:{number}"
        stripped = raw_line.strip()
        if not stripped:
            continue
        title_match = _TITLE_LABEL.fullmatch(stripped)
        if title_match is not None:
            source_value = title_match.group(1).strip()
            if title is None:
                title = source_value
            elif _normalized(title) != _normalized(source_value):
                metadata_conflicts.append(JobMetadataConflict(field="title", selected_value=title, source_value=source_value, source_reference=reference))
            continue
        company_match = _COMPANY_LABEL.fullmatch(stripped)
        if company_match is not None:
            source_value = company_match.group(1).strip()
            if company is None:
                company = source_value
            elif _normalized(company) != _normalized(source_value):
                metadata_conflicts.append(JobMetadataConflict(field="company", selected_value=company, source_value=source_value, source_reference=reference))
            continue
        recognized = _heading(stripped)
        if recognized is not None:
            context = recognized
            continue
        text = _BULLET_PREFIX.sub("", stripped).strip()
        if not text:
            continue
        if context == "responsibility":
            responsibilities.append(_make_requirement(RequirementCategory.RESPONSIBILITY, text, RequirementImportance.UNKNOWN, reference, raw_line))
            continue
        if context == "unknown":
            unresolved.append(UnresolvedJobItem(source_reference=reference, original_text=raw_line, reason_code="unknown_section"))
            continue
        category = _category(context, text)
        if category is None:
            unresolved.append(UnresolvedJobItem(source_reference=reference, original_text=raw_line, reason_code="unknown_section"))
            continue
        importance, observed_values = _importance(context, text)
        requirements.append(_make_requirement(category, text, importance, reference, raw_line))
        if len(observed_values) > 1:
            importance_conflicts.append(JobImportanceConflict(
                category=category.value,
                text=text,
                importance_values=observed_values,
                source_references=(reference,),
                required_source_references=(reference,) if RequirementImportance.REQUIRED in observed_values else (),
                preferred_source_references=(reference,) if RequirementImportance.PREFERRED in observed_values else (),
            ))

    requirements, duplicate_conflicts = _merge_exact(requirements)
    responsibilities, _ = _merge_exact(responsibilities)
    conflicts_by_key: dict[tuple[str, str], JobImportanceConflict] = {}
    for conflict in importance_conflicts + list(duplicate_conflicts):
        key = (conflict.category, _normalized(conflict.text))
        existing = conflicts_by_key.get(key)
        if existing is None:
            conflicts_by_key[key] = conflict
        else:
            conflicts_by_key[key] = existing.model_copy(update={
                "importance_values": tuple(sorted(set(existing.importance_values + conflict.importance_values), key=lambda value: value.value)),
                "source_references": tuple(dict.fromkeys(existing.source_references + conflict.source_references)),
                "required_source_references": tuple(dict.fromkeys(existing.required_source_references + conflict.required_source_references)),
                "preferred_source_references": tuple(dict.fromkeys(existing.preferred_source_references + conflict.preferred_source_references)),
            })
    profile = JobProfile(title=title, company=company, responsibilities=tuple(responsibilities), requirements=tuple(requirements))
    return JobAnalysisResult(
        profile=profile,
        unresolved_items=tuple(sorted(unresolved, key=lambda item: item.source_reference)),
        conflicts=tuple(sorted(conflicts_by_key.values(), key=lambda item: (item.category, item.text))),
        metadata_conflicts=tuple(metadata_conflicts),
    )

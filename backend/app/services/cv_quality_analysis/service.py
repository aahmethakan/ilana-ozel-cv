import unicodedata
from collections.abc import Sequence

from app.domain.career import CareerFact, CareerProfile, VerificationStatus
from app.domain.document import BlockType, CVDocument, SectionType
from app.extraction.career.result import UnresolvedEvidence
from app.services.cv_quality_analysis.schemas import (
    CVQualityContext,
    CVQualityDimension,
    CVQualityDimensionScore,
    CVQualityFinding,
    CVQualityResult,
    FindingSeverity,
)

_TRUSTED_STATUSES = {VerificationStatus.VERIFIED, VerificationStatus.USER_PROVIDED}
_DIMENSION_MAX = {
    CVQualityDimension.COMPLETENESS: 30,
    CVQualityDimension.EVIDENCE: 30,
    CVQualityDimension.STRUCTURE: 20,
    CVQualityDimension.ATS_READINESS: 20,
}
_DIMENSION_ORDER = tuple(_DIMENSION_MAX)


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _trusted(fact: CareerFact) -> bool:
    return fact.verification_status in _TRUSTED_STATUSES


def _references(facts: Sequence[CareerFact]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(fact.source.reference for fact in facts if _trusted(fact) and fact.source.reference))


def _finding(
    code: str,
    dimension: CVQualityDimension,
    severity: FindingSeverity,
    message: str,
    score_impact: int,
    *,
    references: tuple[str, ...] = (),
    hint: str | None = None,
) -> CVQualityFinding:
    return CVQualityFinding(
        code=code,
        dimension=dimension,
        severity=severity,
        message=message,
        score_impact=score_impact,
        evidence_references=references,
        remediation_hint=hint,
    )


def _unresolved_refs(items: Sequence[UnresolvedEvidence], section: SectionType) -> tuple[str, ...]:
    return tuple(item.block_reference for item in items if item.section_type is section)


def _completeness(profile: CareerProfile, unresolved: Sequence[UnresolvedEvidence]) -> tuple[int, list[CVQualityFinding]]:
    findings: list[CVQualityFinding] = []
    score = 0
    if profile.contact is not None:
        score += 6
        findings.append(_finding("structured_contact", CVQualityDimension.COMPLETENESS, FindingSeverity.INFO, "Structured contact information is present.", 6))
    else:
        findings.append(_finding("contact_not_structured", CVQualityDimension.COMPLETENESS, FindingSeverity.IMPROVEMENT, "Contact information is not currently structured in the profile.", -6, hint="Add explicit contact information when available."))
    trusted_skills = [fact for fact in profile.skills if _trusted(fact)]
    if trusted_skills:
        score += 8
        findings.append(_finding("trusted_skills_present", CVQualityDimension.COMPLETENESS, FindingSeverity.INFO, "Explicit trusted skills are present.", 8, references=_references(trusted_skills)))
    else:
        findings.append(_finding("trusted_skills_not_present", CVQualityDimension.COMPLETENESS, FindingSeverity.IMPROVEMENT, "No trusted skills are currently structured in the profile.", -8, hint="Add explicitly supported skills."))
    score += _structured_or_unresolved(
        profile.work_experiences,
        _unresolved_refs(unresolved, SectionType.EXPERIENCE),
        8,
        "experience",
        findings,
    )
    score += _structured_or_unresolved(
        profile.education,
        _unresolved_refs(unresolved, SectionType.EDUCATION),
        8,
        "education",
        findings,
    )
    return score, findings


def _structured_or_unresolved(
    values: Sequence[object],
    unresolved_refs: tuple[str, ...],
    maximum: int,
    name: str,
    findings: list[CVQualityFinding],
) -> int:
    dimension = CVQualityDimension.COMPLETENESS
    if values:
        findings.append(_finding(f"structured_{name}_present", dimension, FindingSeverity.INFO, f"Structured {name} information is present.", maximum))
        return maximum
    if unresolved_refs:
        partial = maximum // 2
        findings.append(_finding(f"{name}_information_unresolved", dimension, FindingSeverity.IMPROVEMENT, f"{name.capitalize()} information could not yet be structured reliably.", -(maximum - partial), references=unresolved_refs, hint="Review unresolved source evidence before treating this information as absent."))
        return partial
    findings.append(_finding(f"{name}_not_structured", dimension, FindingSeverity.IMPROVEMENT, f"No structured {name} information is currently available.", -maximum, hint=f"Add explicit {name} details when available."))
    return 0


def _evidence(profile: CareerProfile) -> tuple[int, list[CVQualityFinding]]:
    findings: list[CVQualityFinding] = []
    score = 0
    unique_skills = {_normalized(fact.statement): fact for fact in profile.skills if _trusted(fact)}
    if unique_skills:
        score += 6
        findings.append(_finding("distinct_trusted_skills", CVQualityDimension.EVIDENCE, FindingSeverity.INFO, "Distinct trusted skills provide explicit evidence.", 6, references=_references(tuple(unique_skills.values()))))
    work_facts = tuple(fact for experience in profile.work_experiences for fact in experience.facts if _trusted(fact))
    if work_facts:
        score += 8
        findings.append(_finding("trusted_experience_facts", CVQualityDimension.EVIDENCE, FindingSeverity.INFO, "Structured experience facts provide concrete responsibility evidence.", 8, references=_references(work_facts)))
    if any(fact.metrics for fact in work_facts):
        score += 10
        findings.append(_finding("explicit_metrics", CVQualityDimension.EVIDENCE, FindingSeverity.INFO, "Explicit measurable evidence is present in structured experience facts.", 10, references=_references(work_facts)))
    else:
        findings.append(_finding("no_structured_metrics", CVQualityDimension.EVIDENCE, FindingSeverity.IMPROVEMENT, "No explicit measurable result is currently structured.", -10, hint="Add only measurable results that can be explicitly supported."))
    if any(fact.skills or fact.tools for fact in work_facts):
        score += 6
        findings.append(_finding("experience_tools_or_skills", CVQualityDimension.EVIDENCE, FindingSeverity.INFO, "Experience facts include explicit tools or skills.", 6, references=_references(work_facts)))
    else:
        findings.append(_finding("no_experience_tools_or_skills", CVQualityDimension.EVIDENCE, FindingSeverity.IMPROVEMENT, "No explicit tools or skills are currently tied to structured experience facts.", -6, hint="Add only tools or skills directly used in the role."))
    return score, findings


def _document_scores(document: CVDocument | None, unresolved: Sequence[UnresolvedEvidence]) -> tuple[int, int, bool, list[CVQualityFinding]]:
    findings: list[CVQualityFinding] = []
    if document is None:
        findings.append(_finding("document_structure_not_evaluated", CVQualityDimension.STRUCTURE, FindingSeverity.INFO, "Document-level structure was not evaluated because no CVDocument was supplied.", 0))
        findings.append(_finding("ats_readiness_not_evaluated", CVQualityDimension.ATS_READINESS, FindingSeverity.INFO, "ATS readability signals were not evaluated because no CVDocument was supplied.", 0))
        return 0, 0, False, findings
    text_blocks = tuple(block for block in document.blocks if block.raw_text.strip())
    recognized_sections = tuple(section for section in document.sections if section.section_type is not SectionType.UNKNOWN)
    bullets = tuple(block for block in document.blocks if block.block_type is BlockType.BULLET)
    structure = 20
    ats = 20
    if not text_blocks:
        structure -= 12
        ats -= 12
        findings.append(_finding("no_machine_readable_text", CVQualityDimension.ATS_READINESS, FindingSeverity.IMPORTANT, "No machine-readable text blocks are available in the document.", -12))
    else:
        findings.append(_finding("machine_readable_text", CVQualityDimension.ATS_READINESS, FindingSeverity.INFO, "Machine-readable text blocks are available.", 0))
    if not recognized_sections:
        structure -= 6
        ats -= 5
        findings.append(_finding("recognized_sections_not_present", CVQualityDimension.STRUCTURE, FindingSeverity.IMPROVEMENT, "Recognized section structure is not currently explicit.", -6, hint="Use clear, standard section headings where appropriate."))
    else:
        findings.append(_finding("recognized_sections_present", CVQualityDimension.STRUCTURE, FindingSeverity.INFO, "Recognized section structure is present.", 0))
    if bullets:
        findings.append(_finding("bullet_structure_present", CVQualityDimension.ATS_READINESS, FindingSeverity.INFO, "Bullet structure is present for machine-readable content.", 0))
    else:
        structure -= 2
        ats -= 3
        findings.append(_finding("bullet_structure_limited", CVQualityDimension.ATS_READINESS, FindingSeverity.IMPROVEMENT, "Explicit bullet structure is limited; this may reduce scanability.", -3, hint="Use concise bullets where they clarify responsibilities or achievements."))
    if unresolved:
        structure -= 2
        findings.append(_finding("unresolved_document_evidence", CVQualityDimension.STRUCTURE, FindingSeverity.IMPROVEMENT, "Some source evidence remains unresolved or structurally ambiguous.", -2, references=tuple(item.block_reference for item in unresolved), hint="Review ambiguous source blocks before drawing conclusions from them."))
    return max(0, structure), max(0, ats), True, findings


def analyze_cv_quality(
    profile: CareerProfile,
    *,
    document: CVDocument | None = None,
    unresolved_evidence: Sequence[UnresolvedEvidence] = (),
    context: CVQualityContext | None = None,
) -> CVQualityResult:
    """Score CV information quality deterministically; no AI, fact creation, or mutation."""

    _ = context
    unresolved = tuple(unresolved_evidence)
    completeness, completeness_findings = _completeness(profile, unresolved)
    evidence, evidence_findings = _evidence(profile)
    structure, ats, document_evaluated, document_findings = _document_scores(document, unresolved)
    scores = {
        CVQualityDimension.COMPLETENESS: completeness,
        CVQualityDimension.EVIDENCE: evidence,
        CVQualityDimension.STRUCTURE: structure,
        CVQualityDimension.ATS_READINESS: ats,
    }
    all_findings = completeness_findings + evidence_findings + document_findings
    ordered_findings = tuple(sorted(all_findings, key=lambda item: (item.dimension.value, item.code, item.evidence_references)))
    dimensions = tuple(
        CVQualityDimensionScore(
            dimension=dimension,
            score=scores[dimension],
            max_score=_DIMENSION_MAX[dimension],
            is_evaluated=document_evaluated or dimension not in {CVQualityDimension.STRUCTURE, CVQualityDimension.ATS_READINESS},
            reason_codes=tuple(item.code for item in ordered_findings if item.dimension is dimension),
        )
        for dimension in _DIMENSION_ORDER
    )
    strengths = tuple(item for item in ordered_findings if item.score_impact > 0)
    improvements = tuple(item for item in ordered_findings if item.severity is not FindingSeverity.INFO and item.score_impact <= 0)
    return CVQualityResult(
        overall_score=sum(scores.values()),
        dimensions=dimensions,
        findings=ordered_findings,
        strengths=strengths,
        improvement_opportunities=improvements,
    )

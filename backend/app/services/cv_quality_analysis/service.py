"""Deterministic CV quality scoring based on candidate-facing CV signals.

This intentionally measures the usefulness of a CV, not whether the parser was
able to produce a model. Certificates and publications add context but are not
prerequisites for a strong score.
"""

import unicodedata
from collections.abc import Sequence

from app.domain.career import CareerFact, CareerProfile, VerificationStatus
from app.domain.document import BlockType, CVDocument, CVSection, DocumentBlock, DocumentFormat, DocumentPage, DocumentSource, SectionType, SourceLocation
from app.extraction.career.result import UnresolvedEvidence
from app.services.draft_review import ReviewedCvDraft
from app.services.public_cv_projection import PublicCvProjection
from app.services.cv_quality_analysis.schemas import (
    CVQualityContext, CVQualityDimension, CVQualityDimensionScore,
    CVQualityFinding, CVQualityResult, FindingSeverity,
)

_TRUSTED_STATUSES = {VerificationStatus.VERIFIED, VerificationStatus.USER_PROVIDED}
_DIMENSION_MAX = {CVQualityDimension.COMPLETENESS: 30, CVQualityDimension.EVIDENCE: 30,
                  CVQualityDimension.STRUCTURE: 20, CVQualityDimension.ATS_READINESS: 20}
_DIMENSION_ORDER = tuple(_DIMENSION_MAX)


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _trusted(fact: CareerFact) -> bool:
    return fact.verification_status in _TRUSTED_STATUSES


def _references(facts: Sequence[CareerFact]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f.source.reference for f in facts if _trusted(f) and f.source.reference))


def _finding(code: str, dimension: CVQualityDimension, severity: FindingSeverity,
             message: str, score_impact: int, *, references: tuple[str, ...] = (),
             hint: str | None = None) -> CVQualityFinding:
    return CVQualityFinding(code=code, dimension=dimension, severity=severity, message=message,
                            score_impact=score_impact, evidence_references=references,
                            remediation_hint=hint)


def _add_presence(findings: list[CVQualityFinding], *, code: str, present: bool,
                  dimension: CVQualityDimension, points: int, message: str,
                  missing_message: str, severity: FindingSeverity = FindingSeverity.IMPROVEMENT,
                  references: tuple[str, ...] = ()) -> int:
    if present:
        findings.append(_finding(code, dimension, FindingSeverity.INFO, message, points, references=references))
        return points
    findings.append(_finding(f"{code}_missing", dimension, severity, missing_message, -points))
    return 0


def _trusted_work_facts(profile: CareerProfile) -> tuple[CareerFact, ...]:
    return tuple(fact for role in profile.work_experiences for fact in role.facts if _trusted(fact))


def _completeness(profile: CareerProfile, unresolved: Sequence[UnresolvedEvidence]) -> tuple[int, list[CVQualityFinding]]:
    findings: list[CVQualityFinding] = []
    score = 0
    contact_values = tuple(value for value in (
        profile.contact.email if profile.contact else None,
        profile.contact.phone if profile.contact else None,
        profile.contact.website if profile.contact else None,
    ) if value is not None)
    score += _add_presence(findings, code="contact_details", present=bool(contact_values),
                           dimension=CVQualityDimension.COMPLETENESS, points=4,
                           message="Contact information is present.", missing_message="Contact information is missing.")
    roles = profile.work_experiences
    role_complete = tuple(role for role in roles if role.title and role.company and role.start_date)
    score += _add_presence(findings, code="work_history", present=bool(roles),
                           dimension=CVQualityDimension.COMPLETENESS, points=5,
                           message="Work history is structured.", missing_message="Work history is missing.")
    if not roles:
        findings.append(_finding("experience_not_structured", CVQualityDimension.COMPLETENESS,
                                 FindingSeverity.IMPROVEMENT, "No structured experience information is available.", 0))
    if roles:
        findings.append(_finding("structured_experience_present", CVQualityDimension.COMPLETENESS,
                                 FindingSeverity.INFO, "Structured experience information is present.", 0))
    score += _add_presence(findings, code="role_details", present=len(role_complete) == len(roles) and bool(roles),
                           dimension=CVQualityDimension.COMPLETENESS, points=3,
                           message="Roles include title, employer, and date evidence.",
                           missing_message="Some roles are missing title, employer, or date evidence.")
    score += _add_presence(findings, code="education", present=bool(profile.education),
                           dimension=CVQualityDimension.COMPLETENESS, points=5,
                           message="Education is structured.", missing_message="Education is missing.")
    if not profile.education:
        findings.append(_finding("education_not_structured", CVQualityDimension.COMPLETENESS,
                                 FindingSeverity.IMPROVEMENT, "No structured education information is available.", 0))
    if profile.education:
        findings.append(_finding("structured_education_present", CVQualityDimension.COMPLETENESS,
                                 FindingSeverity.INFO, "Structured education information is present.", 0))
    skill_facts = tuple(f for f in (*profile.skills, *profile.tools) if _trusted(f))
    score += _add_presence(findings, code="skills_or_tools", present=bool(skill_facts),
                           dimension=CVQualityDimension.COMPLETENESS, points=4,
                           message="Explicit skills or tools are present.", missing_message="Explicit skills or tools are missing.", references=_references(skill_facts))
    if skill_facts:
        findings.append(_finding("trusted_skills_present", CVQualityDimension.COMPLETENESS,
                                 FindingSeverity.INFO, "Explicit trusted skills are present.", 0,
                                 references=_references(skill_facts)))
    score += _add_presence(findings, code="languages", present=bool(profile.languages),
                           dimension=CVQualityDimension.COMPLETENESS, points=3,
                           message="Languages are listed.", missing_message="Languages and proficiency are not listed.")
    score += _add_presence(findings, code="project_or_publication_context", present=bool(profile.projects or profile.publications),
                           dimension=CVQualityDimension.COMPLETENESS, points=2,
                           message="Project or publication context is present.", missing_message="No separate project or publication context is listed.")
    evidence_roles = sum(bool(tuple(f for f in role.facts if _trusted(f))) for role in roles)
    score += _add_presence(findings, code="role_evidence_coverage", present=evidence_roles == len(roles) and bool(roles),
                           dimension=CVQualityDimension.COMPLETENESS, points=4,
                           message="Every listed role has supporting evidence.", missing_message="One or more roles have no supporting bullet or fact evidence.")
    if unresolved:
        unresolved_sections = {item.section_type for item in unresolved}
        if SectionType.EXPERIENCE in unresolved_sections and not roles:
            findings.append(_finding("experience_information_unresolved", CVQualityDimension.COMPLETENESS,
                                     FindingSeverity.IMPROVEMENT, "Experience information could not be structured reliably.", -1,
                                     references=tuple(item.block_reference for item in unresolved if item.section_type is SectionType.EXPERIENCE)))
            score += 2
        if SectionType.EDUCATION in unresolved_sections and not profile.education:
            findings.append(_finding("education_information_unresolved", CVQualityDimension.COMPLETENESS,
                                     FindingSeverity.IMPROVEMENT, "Education information could not be structured reliably.", -1,
                                     references=tuple(item.block_reference for item in unresolved if item.section_type is SectionType.EDUCATION)))
            score += 2
        findings.append(_finding("unresolved_profile_evidence", CVQualityDimension.COMPLETENESS,
                                 FindingSeverity.IMPROVEMENT, "Some source content remains ambiguous.", -1,
                                 references=tuple(item.block_reference for item in unresolved)))
        score = max(0, score - 1)
    return score, findings


def _evidence(profile: CareerProfile) -> tuple[int, list[CVQualityFinding]]:
    findings: list[CVQualityFinding] = []
    roles = profile.work_experiences
    facts = _trusted_work_facts(profile)
    score = _add_presence(findings, code="work_fact_evidence", present=bool(facts),
                          dimension=CVQualityDimension.EVIDENCE, points=8,
                          message="Experience bullets provide responsibility evidence.",
                          missing_message="No trusted responsibility evidence is tied to work history.",
                          severity=FindingSeverity.IMPORTANT, references=_references(facts))
    trusted_profile_skills = tuple(fact for fact in (*profile.skills, *profile.tools) if _trusted(fact))
    if trusted_profile_skills:
        score += 1
        findings.append(_finding("explicit_skill_evidence", CVQualityDimension.EVIDENCE, FindingSeverity.INFO,
                                 "Trusted skills provide explicit evidence.", 1, references=_references(trusted_profile_skills)))
    metric_roles = sum(any(_trusted(f) and f.metrics for f in role.facts) for role in roles)
    metric_points = 8 if roles and metric_roles == len(roles) else 5 if metric_roles >= 2 else 3 if metric_roles else 0
    if metric_points:
        findings.append(_finding("explicit_metrics", CVQualityDimension.EVIDENCE, FindingSeverity.INFO,
                                 "Measurable results are present in experience evidence.", metric_points,
                                 references=_references(tuple(f for f in facts if f.metrics))))
        score += metric_points
    else:
        findings.append(_finding("no_structured_metrics", CVQualityDimension.EVIDENCE, FindingSeverity.IMPROVEMENT,
                                 "No measurable result is currently evidenced.", -8))
    tool_roles = sum(any(_trusted(f) and (f.skills or f.tools) for f in role.facts) for role in roles)
    tool_points = 6 if roles and tool_roles == len(roles) else 4 if tool_roles >= 2 else 2 if tool_roles else 0
    if tool_points:
        findings.append(_finding("role_tool_evidence", CVQualityDimension.EVIDENCE, FindingSeverity.INFO,
                                 "Tools or technical skills are connected to role evidence.", tool_points,
                                 references=_references(tuple(f for f in facts if f.skills or f.tools))))
        score += tool_points
    else:
        findings.append(_finding("no_role_tool_evidence", CVQualityDimension.EVIDENCE, FindingSeverity.IMPROVEMENT,
                                 "Tools or technical skills are not connected to role evidence.", -6))
    project_facts = tuple(f for project in profile.projects for f in project.facts if _trusted(f))
    score += _add_presence(findings, code="project_evidence", present=bool(project_facts),
                           dimension=CVQualityDimension.EVIDENCE, points=3,
                           message="Projects include supporting evidence.", missing_message="Projects are absent or have no supporting evidence.",
                           references=_references(project_facts))
    named_skills = {_normalized(f.statement) for f in (*profile.skills, *profile.tools) if _trusted(f)}
    score += _add_presence(findings, code="skills_breadth", present=len(named_skills) >= 3,
                           dimension=CVQualityDimension.EVIDENCE, points=2,
                           message="A readable range of explicit skills is present.", missing_message="Fewer than three explicit skills or tools are evidenced.")
    score += _add_presence(findings, code="evidence_depth", present=len(facts) >= max(3, len(roles) * 2),
                           dimension=CVQualityDimension.EVIDENCE, points=3,
                           message="Experience evidence has useful depth.", missing_message="Experience evidence is too sparse to show depth.")
    return score, findings


def _document_scores(document: CVDocument | None, unresolved: Sequence[UnresolvedEvidence]) -> tuple[int, int, bool, list[CVQualityFinding]]:
    findings: list[CVQualityFinding] = []
    if document is None:
        findings.extend((_finding("document_structure_not_evaluated", CVQualityDimension.STRUCTURE, FindingSeverity.INFO, "Document structure was not evaluated.", 0),
                         _finding("ats_readiness_not_evaluated", CVQualityDimension.ATS_READINESS, FindingSeverity.INFO, "ATS readiness was not evaluated.", 0)))
        return 0, 0, False, findings
    blocks = tuple(block for block in document.blocks if block.raw_text.strip())
    sections = {section.section_type for section in document.sections if section.section_type is not SectionType.UNKNOWN}
    bullets = tuple(block for block in blocks if block.block_type is BlockType.BULLET)
    structure = 0
    structure += _add_presence(findings, code="machine_readable_text", present=bool(blocks), dimension=CVQualityDimension.STRUCTURE, points=5,
                               message="Machine-readable text is available.", missing_message="No machine-readable text is available.", severity=FindingSeverity.IMPORTANT)
    structure += _add_presence(findings, code="recognized_sections", present=len(sections) >= 2, dimension=CVQualityDimension.STRUCTURE, points=5,
                               message="Clear section structure is available.", missing_message="Clear, standard section headings are limited.")
    structure += _add_presence(findings, code="bullet_structure", present=bool(bullets), dimension=CVQualityDimension.STRUCTURE, points=4,
                               message="Bullets improve scanability.", missing_message="Responsibility and outcome bullets are limited.")
    structure += _add_presence(findings, code="chronological_structure", present=SectionType.EXPERIENCE in sections, dimension=CVQualityDimension.STRUCTURE, points=3,
                               message="Experience section supports chronological reading.", missing_message="Experience chronology is not clearly structured.")
    if unresolved:
        findings.append(_finding("unresolved_document_evidence", CVQualityDimension.STRUCTURE, FindingSeverity.IMPROVEMENT,
                                 "Some source content remains structurally ambiguous.", -3,
                                 references=tuple(item.block_reference for item in unresolved)))
    else:
        structure += 3
        findings.append(_finding("no_structural_ambiguity", CVQualityDimension.STRUCTURE, FindingSeverity.INFO,
                                 "No unresolved structural ambiguity was detected.", 3))
    ats = 0
    ats += _add_presence(findings, code="ats_machine_readable", present=bool(blocks), dimension=CVQualityDimension.ATS_READINESS, points=5,
                         message="Text can be read by an ATS.", missing_message="The document has no machine-readable text.", severity=FindingSeverity.IMPORTANT)
    ats += _add_presence(findings, code="ats_standard_headings", present={SectionType.EXPERIENCE, SectionType.EDUCATION, SectionType.SKILLS} <= sections,
                         dimension=CVQualityDimension.ATS_READINESS, points=5, message="Standard ATS section headings are present.",
                         missing_message="Standard experience, education, and skills headings are incomplete.")
    ats += _add_presence(findings, code="ats_contact", present=SectionType.CONTACT in sections, dimension=CVQualityDimension.ATS_READINESS, points=2,
                         message="A contact section is recognizable.", missing_message="A recognizable contact section is not available.")
    ats += _add_presence(findings, code="ats_experience", present=SectionType.EXPERIENCE in sections, dimension=CVQualityDimension.ATS_READINESS, points=3,
                         message="Experience is recognizable to an ATS.", missing_message="An experience section is not recognizable.")
    ats += _add_presence(findings, code="ats_education", present=SectionType.EDUCATION in sections, dimension=CVQualityDimension.ATS_READINESS, points=2,
                         message="Education is recognizable to an ATS.", missing_message="An education section is not recognizable.")
    ats += _add_presence(findings, code="ats_skills", present=SectionType.SKILLS in sections, dimension=CVQualityDimension.ATS_READINESS, points=3,
                         message="Skills are recognizable to an ATS.", missing_message="A skills section is not recognizable.")
    return max(0, structure), max(0, ats), True, findings


def analyze_cv_quality(profile: CareerProfile, *, document: CVDocument | None = None,
                       unresolved_evidence: Sequence[UnresolvedEvidence] = (),
                       context: CVQualityContext | None = None) -> CVQualityResult:
    """Score CV quality without creating facts or using job-description keywords."""
    _ = context
    unresolved = tuple(unresolved_evidence)
    completeness, completeness_findings = _completeness(profile, unresolved)
    evidence, evidence_findings = _evidence(profile)
    structure, ats, document_evaluated, document_findings = _document_scores(document, unresolved)
    scores = {CVQualityDimension.COMPLETENESS: completeness, CVQualityDimension.EVIDENCE: evidence,
              CVQualityDimension.STRUCTURE: structure, CVQualityDimension.ATS_READINESS: ats}
    findings = tuple(sorted(completeness_findings + evidence_findings + document_findings,
                            key=lambda item: (item.dimension.value, item.code, item.evidence_references)))
    dimensions = tuple(CVQualityDimensionScore(dimension=dimension, score=scores[dimension],
                       max_score=_DIMENSION_MAX[dimension], is_evaluated=document_evaluated or dimension not in {CVQualityDimension.STRUCTURE, CVQualityDimension.ATS_READINESS},
                       reason_codes=tuple(item.code for item in findings if item.dimension is dimension)) for dimension in _DIMENSION_ORDER)
    return CVQualityResult(overall_score=sum(scores.values()), dimensions=dimensions, findings=findings,
                           strengths=tuple(item for item in findings if item.score_impact > 0),
                           improvement_opportunities=tuple(item for item in findings if item.severity is not FindingSeverity.INFO and item.score_impact <= 0))


def analyze_reviewed_cv_quality(profile: CareerProfile, projection: PublicCvProjection) -> CVQualityResult:
    """Reuse the existing formula against only current reviewed public content."""
    reviewed_draft = projection.reviewed_draft
    review = reviewed_draft.review
    skill_texts = {item.text for item in review.skills}
    work_by_identity = {(item.company, item.title): item for item in review.work_entries}
    education_keys = {(item.institution, item.qualification) for item in review.education}
    work = tuple(
        item.model_copy(update={"facts": tuple(fact for fact in item.facts if fact.statement in {claim.text for claim in work_by_identity[(item.company, item.title)].claims})})
        for item in profile.work_experiences if (item.company, item.title) in work_by_identity
    )
    education = tuple(item for item in profile.education if any((item.institution, qualification) in education_keys for qualification in (item.degree, item.field_of_study, None)))
    reviewed_profile = profile.model_copy(update={
        "skills": tuple(item for item in profile.skills if item.statement in skill_texts),
        "tools": tuple(item for item in profile.tools if item.statement in skill_texts),
        "work_experiences": work,
        "education": education,
        "languages": (), "projects": (), "publications": (),
    })
    return analyze_cv_quality(reviewed_profile, document=_reviewed_document(reviewed_draft, reviewed_profile))


def _reviewed_document(reviewed_draft: ReviewedCvDraft, profile: CareerProfile) -> CVDocument:
    """A structural view of the reviewed public CV, not a new CV artifact."""
    review = reviewed_draft.review
    blocks: list[DocumentBlock] = []
    sections: list[CVSection] = []

    def add(section: SectionType, heading: str, values: tuple[str, ...], bullet: bool = False) -> None:
        if not values:
            return
        heading_block = DocumentBlock(raw_text=heading, block_type=BlockType.HEADING, location=SourceLocation(page_number=1, block_index=len(blocks)))
        blocks.append(heading_block)
        references = [heading_block.stable_reference]
        for value in values:
            item = DocumentBlock(raw_text=value, block_type=BlockType.BULLET if bullet else BlockType.PARAGRAPH, location=SourceLocation(page_number=1, block_index=len(blocks)))
            blocks.append(item)
            references.append(item.stable_reference)
        sections.append(CVSection(section_type=section, original_heading=heading, block_references=tuple(references)))

    contact = tuple(value.value for value in (profile.contact.email, profile.contact.phone, profile.contact.website) if value) if profile.contact else ()
    add(SectionType.CONTACT, "CONTACT", contact)
    add(SectionType.SKILLS, "SKILLS", tuple(item.text for item in review.skills), bullet=True)
    work_values = tuple(value for entry in review.work_entries for value in (f"{entry.title} | {entry.company}", *(claim.text for claim in entry.claims)))
    add(SectionType.EXPERIENCE, "WORK EXPERIENCE", work_values, bullet=True)
    add(SectionType.EDUCATION, "EDUCATION", tuple(" | ".join(value for value in (entry.qualification, entry.institution) if value) for entry in review.education))
    return CVDocument(source=DocumentSource(filename="reviewed-cv.pdf", document_format=DocumentFormat.PDF, page_count=1), blocks=tuple(blocks), pages=(DocumentPage(page_number=1, block_references=tuple(block.stable_reference for block in blocks)),), sections=tuple(sections))

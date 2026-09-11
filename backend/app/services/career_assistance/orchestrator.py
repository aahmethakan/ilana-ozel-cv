import json

from app.ai.career import AIInterpretationRequest, AIProvider, EvidenceContext, create_career_fact_candidates
from app.ai.career.schemas import CandidateType
from app.domain.document import CVDocument, SectionType
from app.extraction.career import extract_career_profile
from app.extraction.career.result import UnresolvedEvidence
from app.services.career_assistance.schemas import CareerAssistanceResult, ProcessingIssue

_ELIGIBLE_SECTIONS = {SectionType.EXPERIENCE, SectionType.EDUCATION, SectionType.SKILLS, SectionType.LANGUAGES}
_TARGETS = {SectionType.EXPERIENCE: CandidateType.WORK_EXPERIENCE, SectionType.EDUCATION: CandidateType.EDUCATION, SectionType.SKILLS: CandidateType.SKILL, SectionType.LANGUAGES: CandidateType.LANGUAGE}


def _eligible(item: UnresolvedEvidence, block_text: str) -> bool:
    return item.section_type in _ELIGIBLE_SECTIONS and bool(block_text.strip()) and not block_text.strip().isdigit()


def _request(document: CVDocument, item: UnresolvedEvidence) -> AIInterpretationRequest:
    blocks = {block.stable_reference: block for block in document.blocks}
    evidence = [EvidenceContext(reference=item.block_reference, original_text=blocks[item.block_reference].raw_text, section_type=item.section_type)]
    if item.section_type in {SectionType.EXPERIENCE, SectionType.EDUCATION}:
        for section in document.sections:
            if section.section_type is item.section_type and item.block_reference in section.block_references:
                for reference in section.block_references:
                    if reference != item.block_reference and len(evidence) < 3:
                        block = blocks[reference]
                        if section.original_heading and block.raw_text.strip() == section.original_heading.strip():
                            continue
                        evidence.append(EvidenceContext(reference=reference, original_text=block.raw_text, section_type=item.section_type))
                break
    return AIInterpretationRequest(evidence=tuple(evidence), target_category=_TARGETS.get(item.section_type))


def _candidate_key(candidate: object) -> str:
    return json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def assist_career_extraction(document: CVDocument, provider: AIProvider) -> CareerAssistanceResult:
    """Compose deterministic extraction with isolated, untrusted AI proposal validation."""

    extraction = extract_career_profile(document)
    blocks = {block.stable_reference: block for block in document.blocks}
    requested: set[str] = set()
    interpreted_refs: set[str] = set()
    candidates = []
    rejected = []
    issues = []
    candidate_keys: set[str] = set()
    for item in extraction.unresolved_evidence:
        if item.block_reference in requested or not _eligible(item, blocks[item.block_reference].raw_text):
            continue
        requested.add(item.block_reference)
        request = _request(document, item)
        try:
            response = provider.interpret_career_evidence(request)
        except Exception:
            issues.append(ProcessingIssue(evidence_reference=item.block_reference, issue_code="provider_error", safe_message="AI interpretation could not be completed."))
            continue
        validated = create_career_fact_candidates(document, response, request)
        rejected.extend(validated.rejected_proposals)
        if not validated.candidates:
            issues.append(ProcessingIssue(evidence_reference=item.block_reference, issue_code="no_candidate_returned", safe_message="No safe AI proposal was returned."))
            continue
        for candidate in validated.candidates:
            key = _candidate_key(candidate)
            if key not in candidate_keys:
                candidate_keys.add(key)
                candidates.append(candidate)
            interpreted_refs.update(candidate.evidence_references)
    remaining = tuple(item for item in extraction.unresolved_evidence if item.block_reference not in interpreted_refs)
    return CareerAssistanceResult(deterministic_profile=extraction.profile, deterministic_unresolved_evidence=extraction.unresolved_evidence, ai_candidates=tuple(candidates), rejected_ai_proposals=tuple(rejected), remaining_unresolved_evidence=remaining, processing_issues=tuple(issues))

import json
from collections.abc import Callable

from app.confirmation.structured.schemas import (
    BoolFieldDecision,
    CareerDateFieldDecision,
    EducationCandidate,
    EducationFieldDecisions,
    EducationResolutionResult,
    ResolvedEducation,
    ResolvedWorkExperience,
    StructuredFieldAction,
    StructuredFieldResolutionAudit,
    StructuredFieldValue,
    StructuredRecordResolutionAudit,
    StructuredResolutionStatus,
    TextFieldDecision,
    WholeRecordAction,
    WorkExperienceCandidate,
    WorkExperienceFieldDecisions,
    WorkExperienceResolutionResult,
)
from app.domain.career import FactSource, ProvenancedBool, ProvenancedCareerDate, ProvenancedText, SourceType, VerificationStatus

_TEXT_FIELDS = ("company", "title", "location", "institution", "degree", "field_of_study")
_DATE_FIELDS = ("start_date", "end_date")
_BOOL_FIELDS = ("is_current",)


def _user_source(reference: str, value: object) -> FactSource:
    return FactSource(source_type=SourceType.USER_INPUT, reference=reference, original_text=json.dumps(value.model_dump(mode="json") if hasattr(value, "model_dump") else value, ensure_ascii=False))


def _promoted_value(original: StructuredFieldValue | None, correction: object | None, reference: str, constructor: Callable[..., StructuredFieldValue]) -> StructuredFieldValue:
    value = correction if correction is not None else original.value  # type: ignore[union-attr]
    evidence_sources = original.evidence_sources if original is not None else ()
    return constructor(value=value, verification_status=VerificationStatus.USER_PROVIDED, value_source=_user_source(reference, value), evidence_sources=evidence_sources)


def _resolve_field(field_name: str, original: StructuredFieldValue | None, decision: TextFieldDecision | CareerDateFieldDecision | BoolFieldDecision | None, user_input_reference: str | None) -> tuple[StructuredFieldValue | None, StructuredFieldResolutionAudit, str | None]:
    if decision is None:
        return original, StructuredFieldResolutionAudit(field_name=field_name, original_proposed_value=original, resolved_value=original), None
    if original is None and decision.action is not StructuredFieldAction.CORRECT:
        return None, StructuredFieldResolutionAudit(field_name=field_name, action=decision.action, original_proposed_value=None, corrected_value=decision.corrected_value), f"decision_for_missing_{field_name}"
    if decision.action is StructuredFieldAction.REJECT:
        return None, StructuredFieldResolutionAudit(field_name=field_name, action=decision.action, original_proposed_value=original), None
    if decision.action is StructuredFieldAction.LEAVE_UNRESOLVED:
        return original, StructuredFieldResolutionAudit(field_name=field_name, action=decision.action, original_proposed_value=original, resolved_value=original), None
    if user_input_reference is None:
        return None, StructuredFieldResolutionAudit(field_name=field_name, action=decision.action, original_proposed_value=original, corrected_value=decision.corrected_value), "missing_user_input_reference"
    constructor: Callable[..., StructuredFieldValue]
    if field_name in _TEXT_FIELDS:
        constructor = ProvenancedText
    elif field_name in _DATE_FIELDS:
        constructor = ProvenancedCareerDate
    else:
        constructor = ProvenancedBool
    resolved = _promoted_value(original, decision.corrected_value, user_input_reference, constructor)
    return resolved, StructuredFieldResolutionAudit(field_name=field_name, action=decision.action, original_proposed_value=original, corrected_value=decision.corrected_value, resolved_value=resolved), None


def _work_audit(candidate: WorkExperienceCandidate, audits: tuple[StructuredFieldResolutionAudit, ...], whole_action: WholeRecordAction | None = None) -> StructuredRecordResolutionAudit:
    return StructuredRecordResolutionAudit(candidate_id=candidate.candidate_id, record_id=candidate.record_id, record_type=candidate.record_type, origin=candidate.origin, whole_record_action=whole_action, field_audits=audits)


def _education_audit(candidate: EducationCandidate, audits: tuple[StructuredFieldResolutionAudit, ...], whole_action: WholeRecordAction | None = None) -> StructuredRecordResolutionAudit:
    return StructuredRecordResolutionAudit(candidate_id=candidate.candidate_id, record_id=candidate.record_id, record_type=candidate.record_type, origin=candidate.origin, whole_record_action=whole_action, field_audits=audits)


def resolve_work_experience_candidate(candidate: WorkExperienceCandidate, decisions: WorkExperienceFieldDecisions, *, user_input_reference: str | None = None, whole_record_action: WholeRecordAction | None = None) -> WorkExperienceResolutionResult:
    fields = ("company", "title", "location", "start_date", "end_date", "is_current")
    if whole_record_action is WholeRecordAction.REJECT_RECORD:
        audits = tuple(StructuredFieldResolutionAudit(field_name=name, original_proposed_value=getattr(candidate, name)) for name in fields)
        return WorkExperienceResolutionResult(candidate=candidate, status=StructuredResolutionStatus.REJECTED, audit=_work_audit(candidate, audits, whole_record_action))
    values: dict[str, StructuredFieldValue | None] = {}
    audits: list[StructuredFieldResolutionAudit] = []
    issues: list[str] = []
    for name in fields:
        value, audit, issue = _resolve_field(name, getattr(candidate, name), getattr(decisions, name), user_input_reference)
        values[name] = value
        audits.append(audit)
        if issue:
            issues.append(issue)
    record = ResolvedWorkExperience(record_id=candidate.record_id, **values)
    if record.is_current and record.is_current.is_claim_usable and record.is_current.value and record.end_date and record.end_date.is_claim_usable:
        issues.append("current_role_has_usable_end_date")
    if record.start_date and record.start_date.is_claim_usable and record.end_date and record.end_date.is_claim_usable and record.start_date.value.definitely_after(record.end_date.value):
        issues.append("start_date_definitely_after_end_date")
    audit = _work_audit(candidate, tuple(audits))
    if issues:
        return WorkExperienceResolutionResult(candidate=candidate, status=StructuredResolutionStatus.INVALID, audit=audit, issue_codes=tuple(dict.fromkeys(issues)))
    status = StructuredResolutionStatus.RESOLVED if record.has_minimum_trusted_identity else StructuredResolutionStatus.PARTIALLY_RESOLVED
    return WorkExperienceResolutionResult(candidate=candidate, status=status, audit=audit, resolved_record=record)


def resolve_education_candidate(candidate: EducationCandidate, decisions: EducationFieldDecisions, *, user_input_reference: str | None = None, whole_record_action: WholeRecordAction | None = None) -> EducationResolutionResult:
    fields = ("institution", "degree", "field_of_study", "start_date", "end_date")
    if whole_record_action is WholeRecordAction.REJECT_RECORD:
        audits = tuple(StructuredFieldResolutionAudit(field_name=name, original_proposed_value=getattr(candidate, name)) for name in fields)
        return EducationResolutionResult(candidate=candidate, status=StructuredResolutionStatus.REJECTED, audit=_education_audit(candidate, audits, whole_record_action))
    values: dict[str, StructuredFieldValue | None] = {}
    audits: list[StructuredFieldResolutionAudit] = []
    issues: list[str] = []
    for name in fields:
        value, audit, issue = _resolve_field(name, getattr(candidate, name), getattr(decisions, name), user_input_reference)
        values[name] = value
        audits.append(audit)
        if issue:
            issues.append(issue)
    record = ResolvedEducation(record_id=candidate.record_id, **values)
    if record.start_date and record.start_date.is_claim_usable and record.end_date and record.end_date.is_claim_usable and record.start_date.value.definitely_after(record.end_date.value):
        issues.append("start_date_definitely_after_end_date")
    audit = _education_audit(candidate, tuple(audits))
    if issues:
        return EducationResolutionResult(candidate=candidate, status=StructuredResolutionStatus.INVALID, audit=audit, issue_codes=tuple(dict.fromkeys(issues)))
    status = StructuredResolutionStatus.RESOLVED if record.has_minimum_trusted_identity else StructuredResolutionStatus.PARTIALLY_RESOLVED
    return EducationResolutionResult(candidate=candidate, status=status, audit=audit, resolved_record=record)

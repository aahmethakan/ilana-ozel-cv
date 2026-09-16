import hashlib
import json
from collections.abc import Sequence

from app.confirmation.structured.schemas import (
    EducationResolutionResult,
    StructuredFieldAction,
    StructuredRecordType,
    StructuredResolutionStatus,
    WorkExperienceResolutionResult,
)
from app.domain.career import SourceType, VerificationStatus
from app.extraction.career import UnresolvedEvidence
from app.services.evidence_convergence.schemas import (
    EducationEvidenceResolutionBinding,
    EvidenceConvergenceBasis,
    EvidenceConvergenceItem,
    EvidenceConvergenceResult,
    EvidenceConvergenceState,
    EvidenceResolutionBinding,
    WorkEvidenceResolutionBinding,
)
from app.services.structured_profile.schemas import StructuredCareerProfileAssemblyResult


_WORK_FIELD_ORDER = ("company", "title", "location", "start_date", "end_date", "is_current")
_EDUCATION_FIELD_ORDER = ("institution", "degree", "field_of_study", "start_date", "end_date")


def unresolved_evidence_key(evidence: UnresolvedEvidence) -> str:
    """Derive a stable convergence identity without mutating extraction evidence."""

    payload = evidence.model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"unresolved:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _binding_identity(binding: EvidenceResolutionBinding) -> tuple[str, str, str, str, str]:
    return (
        binding.evidence_key,
        binding.record_type.value,
        binding.record_id,
        binding.candidate_id,
        binding.field_name.value,
    )


def _field_rank(binding: EvidenceResolutionBinding) -> int:
    fields = _WORK_FIELD_ORDER if binding.record_type is StructuredRecordType.WORK_EXPERIENCE else _EDUCATION_FIELD_ORDER
    return fields.index(binding.field_name.value)


def _item(binding: EvidenceResolutionBinding, state: EvidenceConvergenceState, basis: EvidenceConvergenceBasis, *issue_codes: str) -> EvidenceConvergenceItem:
    return EvidenceConvergenceItem(
        evidence_key=binding.evidence_key,
        record_type=binding.record_type,
        record_id=binding.record_id,
        candidate_id=binding.candidate_id,
        field_name=binding.field_name,
        state=state,
        basis=basis,
        issue_codes=issue_codes,
        related_record_ids=(binding.record_id,),
        related_candidate_ids=(binding.candidate_id,),
    )


def _conflict(binding: EvidenceResolutionBinding, *issue_codes: str) -> EvidenceConvergenceItem:
    return _item(binding, EvidenceConvergenceState.CONFLICT, EvidenceConvergenceBasis.STRUCTURED_CONFLICT, *issue_codes)


def _binding_conflict(bindings: Sequence[EvidenceResolutionBinding]) -> EvidenceConvergenceItem:
    first = bindings[0]
    return EvidenceConvergenceItem(
        evidence_key=first.evidence_key,
        record_type=first.record_type,
        field_name=first.field_name,
        state=EvidenceConvergenceState.CONFLICT,
        basis=EvidenceConvergenceBasis.STRUCTURED_CONFLICT,
        issue_codes=("conflicting_evidence_field_bindings",),
        related_record_ids=tuple(sorted({item.record_id for item in bindings})),
        related_candidate_ids=tuple(sorted({item.candidate_id for item in bindings})),
    )


def _result_index(results: Sequence[WorkExperienceResolutionResult] | Sequence[EducationResolutionResult]):
    index: dict[tuple[str, str], WorkExperienceResolutionResult | EducationResolutionResult] = {}
    for result in results:
        key = (result.candidate.record_id, result.candidate.candidate_id)
        if key in index and index[key] != result:
            raise ValueError("Multiple different structured resolution results share a record and candidate lineage.")
        index[key] = result
    return index


def _is_profile_admitted(binding: EvidenceResolutionBinding, profile_result: StructuredCareerProfileAssemblyResult) -> bool:
    entries = (
        profile_result.profile.work_experiences
        if binding.record_type is StructuredRecordType.WORK_EXPERIENCE
        else profile_result.profile.education
    )
    return any(entry.record.record_id == binding.record_id and entry.candidate_id == binding.candidate_id for entry in entries)


def _is_profile_conflicted(binding: EvidenceResolutionBinding, profile_result: StructuredCareerProfileAssemblyResult) -> bool:
    return any(conflict.record_type is binding.record_type and conflict.record_id == binding.record_id for conflict in profile_result.conflicts)


def _converge_binding(
    binding: EvidenceResolutionBinding,
    resolution: WorkExperienceResolutionResult | EducationResolutionResult,
    profile_result: StructuredCareerProfileAssemblyResult,
) -> EvidenceConvergenceItem:
    if resolution.audit.record_type is not binding.record_type or resolution.audit.record_id != binding.record_id or resolution.audit.candidate_id != binding.candidate_id:
        return _conflict(binding, "audit_lineage_mismatch")
    if _is_profile_conflicted(binding, profile_result):
        return _conflict(binding, "profile_record_conflict")
    if resolution.status is StructuredResolutionStatus.REJECTED:
        return _item(binding, EvidenceConvergenceState.REJECTED, EvidenceConvergenceBasis.USER_REJECTED)
    if resolution.status is StructuredResolutionStatus.INVALID:
        return _conflict(binding, "invalid_structured_resolution")
    if resolution.resolved_record is None:
        return _conflict(binding, "missing_resolved_record")
    if not _is_profile_admitted(binding, profile_result):
        return _conflict(binding, "resolution_not_admitted_to_profile")

    audit = next((item for item in resolution.audit.field_audits if item.field_name == binding.field_name.value), None)
    if audit is None:
        return _conflict(binding, "audit_field_missing")
    current_value = getattr(resolution.resolved_record, binding.field_name.value)
    if audit.action is StructuredFieldAction.REJECT:
        if current_value is not None or audit.resolved_value is not None:
            return _conflict(binding, "audit_current_value_mismatch")
        return _item(binding, EvidenceConvergenceState.REJECTED, EvidenceConvergenceBasis.USER_REJECTED)
    if audit.resolved_value != current_value:
        return _conflict(binding, "audit_current_value_mismatch")
    if current_value is None or not current_value.is_claim_usable:
        return _item(binding, EvidenceConvergenceState.STILL_UNRESOLVED, EvidenceConvergenceBasis.UNRESOLVED)
    if audit.action is StructuredFieldAction.ACCEPT:
        if current_value.verification_status is not VerificationStatus.USER_PROVIDED or current_value.value_source.source_type is not SourceType.USER_INPUT:
            return _conflict(binding, "accepted_field_not_user_provided")
        return _item(binding, EvidenceConvergenceState.RESOLVED, EvidenceConvergenceBasis.USER_CONFIRMED)
    if audit.action is StructuredFieldAction.CORRECT:
        if current_value.verification_status is not VerificationStatus.USER_PROVIDED or current_value.value_source.source_type is not SourceType.USER_INPUT:
            return _conflict(binding, "corrected_field_not_user_provided")
        return _item(binding, EvidenceConvergenceState.RESOLVED, EvidenceConvergenceBasis.USER_CORRECTED)
    if current_value.verification_status is VerificationStatus.VERIFIED:
        return _item(binding, EvidenceConvergenceState.RESOLVED, EvidenceConvergenceBasis.PREEXISTING_VERIFIED)
    if current_value.verification_status is VerificationStatus.USER_PROVIDED:
        return _item(binding, EvidenceConvergenceState.RESOLVED, EvidenceConvergenceBasis.PREEXISTING_USER_PROVIDED)
    return _item(binding, EvidenceConvergenceState.STILL_UNRESOLVED, EvidenceConvergenceBasis.UNRESOLVED)


def converge_structured_evidence(
    *,
    unresolved_evidence: Sequence[UnresolvedEvidence],
    bindings: Sequence[EvidenceResolutionBinding],
    work_results: Sequence[WorkExperienceResolutionResult] = (),
    education_results: Sequence[EducationResolutionResult] = (),
    profile_result: StructuredCareerProfileAssemblyResult,
) -> EvidenceConvergenceResult:
    """Converge only explicitly bound structured fields; no text or record-ID matching is performed."""

    known_evidence_keys = {unresolved_evidence_key(item) for item in unresolved_evidence}
    for binding in bindings:
        if binding.evidence_key not in known_evidence_keys:
            raise ValueError("Binding refers to unknown unresolved evidence.")

    work_index = _result_index(work_results)
    education_index = _result_index(education_results)
    deduplicated: dict[tuple[str, str, str, str, str], EvidenceResolutionBinding] = {}
    for binding in bindings:
        deduplicated.setdefault(_binding_identity(binding), binding)
    grouped: dict[tuple[str, str, str], list[EvidenceResolutionBinding]] = {}
    for binding in deduplicated.values():
        grouped.setdefault((binding.evidence_key, binding.record_type.value, binding.field_name.value), []).append(binding)

    items: list[EvidenceConvergenceItem] = []
    bound_keys: set[str] = set()
    for evidence in unresolved_evidence:
        evidence_key = unresolved_evidence_key(evidence)
        evidence_groups = [group for (key, _, _), group in grouped.items() if key == evidence_key]
        for group in sorted(evidence_groups, key=lambda values: (_field_rank(values[0]), values[0].field_name.value)):
            bound_keys.add(evidence_key)
            if len(group) != 1:
                items.append(_binding_conflict(group))
                continue
            binding = group[0]
            index = work_index if binding.record_type is StructuredRecordType.WORK_EXPERIENCE else education_index
            resolution = index.get((binding.record_id, binding.candidate_id))
            if resolution is None:
                raise ValueError("Binding does not match a supplied structured resolution result.")
            items.append(_converge_binding(binding, resolution, profile_result))
    return EvidenceConvergenceResult(
        items=tuple(items),
        unbound_unresolved_evidence=tuple(item for item in unresolved_evidence if unresolved_evidence_key(item) not in bound_keys),
    )

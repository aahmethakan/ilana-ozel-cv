from collections.abc import Sequence

from app.confirmation.structured.schemas import (
    EducationResolutionResult,
    WorkExperienceResolutionResult,
    StructuredRecordType,
    StructuredResolutionStatus,
)
from app.services.structured_profile.schemas import (
    SkippedStructuredRecord,
    StructuredCareerProfile,
    StructuredCareerProfileAssemblyResult,
    StructuredEducationEntry,
    StructuredRecordConflict,
    StructuredWorkExperienceEntry,
)

_ADMISSIBLE_STATUSES = {StructuredResolutionStatus.RESOLVED, StructuredResolutionStatus.PARTIALLY_RESOLVED}


def _skip(record_type: StructuredRecordType, result: WorkExperienceResolutionResult | EducationResolutionResult, reason_code: str) -> SkippedStructuredRecord:
    return SkippedStructuredRecord(
        record_type=record_type,
        candidate_id=result.candidate.candidate_id,
        record_id=result.candidate.record_id,
        resolution_status=result.status,
        reason_code=reason_code,
    )


def _valid_results(record_type: StructuredRecordType, results: Sequence[WorkExperienceResolutionResult] | Sequence[EducationResolutionResult]):
    accepted: list[WorkExperienceResolutionResult | EducationResolutionResult] = []
    skipped: list[SkippedStructuredRecord] = []
    for result in results:
        if result.status is StructuredResolutionStatus.REJECTED:
            skipped.append(_skip(record_type, result, "rejected_resolution"))
        elif result.status is StructuredResolutionStatus.INVALID:
            skipped.append(_skip(record_type, result, "invalid_resolution"))
        elif result.resolved_record is None:
            skipped.append(_skip(record_type, result, "missing_resolved_record"))
        elif result.status not in _ADMISSIBLE_STATUSES:
            skipped.append(_skip(record_type, result, "non_admissible_resolution_status"))
        else:
            accepted.append(result)
    return accepted, skipped


def _deduplicate(record_type: StructuredRecordType, results: Sequence[WorkExperienceResolutionResult] | Sequence[EducationResolutionResult]):
    groups: dict[str, list[WorkExperienceResolutionResult | EducationResolutionResult]] = {}
    for result in results:
        groups.setdefault(result.candidate.record_id, []).append(result)
    retained: list[WorkExperienceResolutionResult | EducationResolutionResult] = []
    conflicts: list[StructuredRecordConflict] = []
    for record_id, grouped in groups.items():
        first = grouped[0]
        assert first.resolved_record is not None
        if all(
            item.status is first.status
            and item.resolved_record == first.resolved_record
            and item.candidate.candidate_id == first.candidate.candidate_id
            for item in grouped[1:]
        ):
            retained.append(first)
        else:
            same_state = all(item.status is first.status and item.resolved_record == first.resolved_record for item in grouped[1:])
            conflicts.append(
                StructuredRecordConflict(
                    record_type=record_type,
                    record_id=record_id,
                    candidate_ids=tuple(item.candidate.candidate_id for item in grouped),
                    reason_code=(
                        "duplicate_record_id_conflicting_lineage"
                        if same_state
                        else "duplicate_record_id_conflicting_state"
                    ),
                )
            )
    return retained, conflicts


def assemble_structured_career_profile(
    *,
    work_results: Sequence[WorkExperienceResolutionResult] = (),
    education_results: Sequence[EducationResolutionResult] = (),
) -> StructuredCareerProfileAssemblyResult:
    """Assemble only valid structured resolution outputs without flattening their provenance."""

    valid_work, skipped_work = _valid_results(StructuredRecordType.WORK_EXPERIENCE, work_results)
    valid_education, skipped_education = _valid_results(StructuredRecordType.EDUCATION, education_results)
    retained_work, work_conflicts = _deduplicate(StructuredRecordType.WORK_EXPERIENCE, valid_work)
    retained_education, education_conflicts = _deduplicate(StructuredRecordType.EDUCATION, valid_education)
    work_entries = tuple(
        StructuredWorkExperienceEntry(record=result.resolved_record, resolution_status=result.status, candidate_id=result.candidate.candidate_id)
        for result in retained_work
        if result.resolved_record is not None
    )
    education_entries = tuple(
        StructuredEducationEntry(record=result.resolved_record, resolution_status=result.status, candidate_id=result.candidate.candidate_id)
        for result in retained_education
        if result.resolved_record is not None
    )
    profile = StructuredCareerProfile(work_experiences=work_entries, education=education_entries)
    return StructuredCareerProfileAssemblyResult(
        profile=profile,
        applied_record_ids=tuple(entry.record.record_id for entry in work_entries) + tuple(entry.record.record_id for entry in education_entries),
        skipped_records=tuple(skipped_work + skipped_education),
        conflicts=tuple(work_conflicts + education_conflicts),
    )

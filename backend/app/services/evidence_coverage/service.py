from collections.abc import Sequence

from app.confirmation.structured.schemas import StructuredRecordType
from app.extraction.career import UnresolvedEvidence
from app.services.evidence_convergence import unresolved_evidence_key
from app.services.evidence_convergence.schemas import EvidenceConvergenceItem, EvidenceConvergenceResult, EvidenceConvergenceState
from app.services.evidence_coverage.schemas import (
    EducationEvidenceCoverageDeclaration,
    EvidenceCoverageDeclaration,
    EvidenceCoverageFieldState,
    EvidenceCoverageItem,
    EvidenceCoverageOverallState,
    EvidenceCoverageResult,
    EvidenceCoverageStatus,
    WorkEvidenceCoverageDeclaration,
    canonical_coverage_fields,
    computed_coverage_id,
)


_WORK_FIELD_ORDER = ("company", "title", "location", "start_date", "end_date", "is_current")
_EDUCATION_FIELD_ORDER = ("institution", "degree", "field_of_study", "start_date", "end_date")


def _field_order(record_type: StructuredRecordType, fields: Sequence[object]) -> tuple[object, ...]:
    return canonical_coverage_fields(record_type, tuple(fields))


def _lineage(item: EvidenceConvergenceItem) -> tuple[str, StructuredRecordType, str, str] | None:
    if item.record_id is None or item.candidate_id is None or item.record_type is None:
        return None
    return item.evidence_key, item.record_type, item.record_id, item.candidate_id


def _item_matches_lineage(item: EvidenceConvergenceItem, lineage: tuple[str, StructuredRecordType, str, str]) -> bool:
    evidence_key, record_type, record_id, candidate_id = lineage
    if item.evidence_key != evidence_key or item.record_type is not record_type:
        return False
    if item.record_id == record_id and item.candidate_id == candidate_id:
        return True
    return record_id in item.related_record_ids and candidate_id in item.related_candidate_ids


def coverage_id(declaration: EvidenceCoverageDeclaration) -> str:
    return computed_coverage_id(
        evidence_key=declaration.evidence_key, record_type=declaration.record_type,
        record_id=declaration.record_id, candidate_id=declaration.candidate_id,
        covered_fields=declaration.covered_fields, coverage_status=declaration.coverage_status,
    )


def _validate_declarations(declarations: Sequence[EvidenceCoverageDeclaration], known_keys: set[str]) -> tuple[EvidenceCoverageDeclaration, ...]:
    grouped: dict[tuple[str, StructuredRecordType, str, str], list[EvidenceCoverageDeclaration]] = {}
    for declaration in declarations:
        if declaration.evidence_key not in known_keys:
            raise ValueError("Coverage declaration refers to unknown unresolved evidence.")
        key = (declaration.evidence_key, declaration.record_type, declaration.record_id, declaration.candidate_id)
        grouped.setdefault(key, []).append(declaration)
    result: list[EvidenceCoverageDeclaration] = []
    for group in grouped.values():
        first = group[0]
        canonical_first = (first.coverage_status, _field_order(first.record_type, first.covered_fields))
        if any((item.coverage_status, _field_order(item.record_type, item.covered_fields)) != canonical_first for item in group[1:]):
            raise ValueError("Conflicting evidence coverage declarations share a lineage.")
        result.append(first)
    return tuple(result)


def _states_for_lineage(convergence: EvidenceConvergenceResult, lineage: tuple[str, StructuredRecordType, str, str]):
    matches = [item for item in convergence.items if _item_matches_lineage(item, lineage)]
    return {item.field_name: item.state for item in matches}


def _overall(status: EvidenceCoverageStatus, states: Sequence[EvidenceConvergenceState]) -> EvidenceCoverageOverallState:
    if status is EvidenceCoverageStatus.DECLARED_PARTIAL:
        return EvidenceCoverageOverallState.PARTIAL
    if all(state in {EvidenceConvergenceState.RESOLVED, EvidenceConvergenceState.REJECTED} for state in states):
        return EvidenceCoverageOverallState.COMPLETE_AND_CLOSED
    return EvidenceCoverageOverallState.COMPLETE_BUT_OPEN


def evaluate_evidence_coverage(
    *,
    unresolved_evidence: Sequence[UnresolvedEvidence],
    convergence_result: EvidenceConvergenceResult,
    declarations: Sequence[EvidenceCoverageDeclaration],
) -> EvidenceCoverageResult:
    """Evaluate explicit structured-binding coverage; never infer whole-source semantic completeness."""

    known_keys = {item.evidence_key for item in convergence_result.items}
    known_keys.update(unresolved_evidence_key(item) for item in unresolved_evidence)
    validated = _validate_declarations(declarations, known_keys)
    declared_lineages = {(item.evidence_key, item.record_type, item.record_id, item.candidate_id) for item in validated}

    items: list[EvidenceCoverageItem] = []
    for declaration in validated:
        lineage = (declaration.evidence_key, declaration.record_type, declaration.record_id, declaration.candidate_id)
        states = _states_for_lineage(convergence_result, lineage)
        covered_fields = _field_order(declaration.record_type, declaration.covered_fields)
        if set(covered_fields) != set(states):
            raise ValueError("Coverage declaration fields must exactly match the bound convergence fields for its lineage.")
        snapshots = tuple(EvidenceCoverageFieldState(field_name=field, convergence_state=states[field]) for field in covered_fields)
        items.append(EvidenceCoverageItem(
            coverage_id=coverage_id(declaration), evidence_key=declaration.evidence_key,
            record_type=declaration.record_type, record_id=declaration.record_id, candidate_id=declaration.candidate_id,
            covered_fields=covered_fields, coverage_status=declaration.coverage_status,
            field_states=snapshots, overall_state=_overall(declaration.coverage_status, tuple(states[field] for field in covered_fields)),
        ))

    seen_lineages: set[tuple[str, StructuredRecordType, str, str]] = set()
    for item in convergence_result.items:
        lineage = _lineage(item)
        if lineage is None or lineage in seen_lineages or lineage in declared_lineages:
            continue
        seen_lineages.add(lineage)
        states = _states_for_lineage(convergence_result, lineage)
        fields = _field_order(lineage[1], tuple(states))
        items.append(EvidenceCoverageItem(
            evidence_key=lineage[0], record_type=lineage[1], record_id=lineage[2], candidate_id=lineage[3],
            covered_fields=fields, field_states=tuple(EvidenceCoverageFieldState(field_name=field, convergence_state=states[field]) for field in fields),
            overall_state=EvidenceCoverageOverallState.UNDECLARED,
        ))
    bound_keys = {item.evidence_key for item in convergence_result.items}
    return EvidenceCoverageResult(
        items=tuple(items),
        unbound_unresolved_evidence=tuple(
            item for item in unresolved_evidence if unresolved_evidence_key(item) not in bound_keys
        ),
    )

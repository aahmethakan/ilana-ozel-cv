from collections import OrderedDict

from app.domain.job import RequirementImportance
from app.services.job_match import JobMatchResult, RequirementMatchResult, RequirementMatchStatus, RequirementMatchType
from app.services.job_match_score.schemas import (
    JobMatchScoreBreakdown,
    JobMatchScoreFinding,
    JobMatchScoreFindingSeverity,
    JobMatchScoreResult,
    JobMatchScoringPolicy,
)

DEFAULT_JOB_MATCH_SCORING_POLICY = JobMatchScoringPolicy()


def _identity(result: RequirementMatchResult) -> str:
    return result.requirement.requirement_id


def _deduplicated_results(match_result: JobMatchResult) -> tuple[tuple[RequirementMatchResult, ...], int, int]:
    grouped: OrderedDict[str, list[RequirementMatchResult]] = OrderedDict()
    for result in match_result.requirement_results:
        grouped.setdefault(_identity(result), []).append(result)

    output: list[RequirementMatchResult] = []
    duplicate_count = 0
    conflicting_count = 0
    for results in grouped.values():
        first = results[0]
        duplicate_count += len(results) - 1
        statuses = {item.status for item in results}
        importance_values = {item.requirement.importance for item in results}
        merged_requirement = first.requirement.model_copy(update={
            "importance": first.requirement.importance if len(importance_values) == 1 else RequirementImportance.UNKNOWN,
            "source_references": tuple(dict.fromkeys(reference for item in results for reference in item.requirement.source_references)),
            "source_texts": tuple(dict.fromkeys(text for item in results for text in item.requirement.source_texts)),
        })
        if len(statuses) == 1:
            output.append(first.model_copy(update={"requirement": merged_requirement}))
            continue
        conflicting_count += 1
        output.append(first.model_copy(update={
            "requirement": merged_requirement,
            "status": RequirementMatchStatus.NOT_EVALUABLE,
            "matched_evidence_references": (),
            "reason_code": "conflicting_duplicate_match_results",
            "explanation": "Conflicting duplicate match results are not included in the deterministic score.",
        }))
    return tuple(output), duplicate_count, conflicting_count


def _weight(importance: RequirementImportance, policy: JobMatchScoringPolicy) -> int:
    if importance is RequirementImportance.REQUIRED:
        return policy.required_weight
    if importance is RequirementImportance.PREFERRED:
        return policy.preferred_weight
    return policy.unknown_weight


def _status_units(status: RequirementMatchStatus, policy: JobMatchScoringPolicy) -> int | None:
    if status is RequirementMatchStatus.MATCHED:
        return policy.matched_units
    if status is RequirementMatchStatus.PARTIAL:
        return policy.partial_units
    if status is RequirementMatchStatus.NOT_EVIDENCED:
        return policy.not_evidenced_units
    return None


def _result_units(result: RequirementMatchResult, policy: JobMatchScoringPolicy) -> int | None:
    units = _status_units(result.status, policy)
    # Controlled equivalence confirms owned evidence but is intentionally worth less
    # than a literal requirement match. It never changes candidate evidence.
    if result.match_type is RequirementMatchType.CONTROLLED_SEMANTIC and units is not None:
        return min(units, policy.partial_units)
    return units


def _rounded_percent(numerator: int, denominator: int) -> int | None:
    if denominator == 0:
        return None
    return (100 * numerator + denominator // 2) // denominator


def _score(results: tuple[RequirementMatchResult, ...], policy: JobMatchScoringPolicy) -> int | None:
    earned = 0
    possible = 0
    for result in results:
        units = _result_units(result, policy)
        if units is None:
            continue
        weight = _weight(result.requirement.importance, policy)
        earned += weight * units
        possible += weight * policy.matched_units
    return _rounded_percent(earned, possible)


def _coverage(results: tuple[RequirementMatchResult, ...]) -> int | None:
    if not results:
        return None
    evaluated = sum(result.status is not RequirementMatchStatus.NOT_EVALUABLE for result in results)
    return _rounded_percent(evaluated, len(results))


def _finding(code: str, severity: JobMatchScoreFindingSeverity, message: str) -> JobMatchScoreFinding:
    return JobMatchScoreFinding(code=code, severity=severity, message=message)


def calculate_job_match_score(match_result: JobMatchResult) -> JobMatchScoreResult:
    """Aggregate existing match classifications without making new match decisions."""

    policy = DEFAULT_JOB_MATCH_SCORING_POLICY
    results, duplicate_count, conflicting_duplicate_count = _deduplicated_results(match_result)
    required = tuple(item for item in results if item.requirement.importance is RequirementImportance.REQUIRED)
    preferred = tuple(item for item in results if item.requirement.importance is RequirementImportance.PREFERRED)
    unknown = tuple(item for item in results if item.requirement.importance is RequirementImportance.UNKNOWN)
    evaluated = tuple(item for item in results if item.status is not RequirementMatchStatus.NOT_EVALUABLE)
    weighted_earned = sum(
        _weight(item.requirement.importance, policy) * (_result_units(item, policy) or 0)
        for item in evaluated
    )
    weighted_possible = sum(
        _weight(item.requirement.importance, policy) * policy.matched_units
        for item in evaluated
    )
    breakdown = JobMatchScoreBreakdown(
        matched_count=sum(item.status is RequirementMatchStatus.MATCHED for item in results),
        partial_count=sum(item.status is RequirementMatchStatus.PARTIAL for item in results),
        not_evidenced_count=sum(item.status is RequirementMatchStatus.NOT_EVIDENCED for item in results),
        not_evaluable_count=sum(item.status is RequirementMatchStatus.NOT_EVALUABLE for item in results),
        required_count=len(required),
        preferred_count=len(preferred),
        unknown_importance_count=len(unknown),
        unknown_importance_evaluable_count=sum(item.status is not RequirementMatchStatus.NOT_EVALUABLE for item in unknown),
        evaluated_count=len(evaluated),
        structured_requirement_count=len(results),
        unresolved_job_item_count=len(match_result.unresolved_job_items),
        duplicate_result_count=duplicate_count,
        conflicting_duplicate_result_count=conflicting_duplicate_count,
        weighted_earned_units=weighted_earned,
        weighted_possible_units=weighted_possible,
    )
    findings: list[JobMatchScoreFinding] = []
    coverage = _coverage(results)
    if coverage is None:
        findings.append(_finding("no_structured_requirements", JobMatchScoreFindingSeverity.LIMITATION, "No structured job requirements were available for deterministic evaluation."))
    elif coverage == 100:
        findings.append(_finding("coverage_complete", JobMatchScoreFindingSeverity.INFO, "All structured job requirements were evaluated by the deterministic matcher."))
    else:
        findings.append(_finding("coverage_incomplete", JobMatchScoreFindingSeverity.LIMITATION, "Some structured job requirements could not be evaluated safely and are excluded from the match score."))
    if not evaluated and results:
        findings.append(_finding("no_evaluable_requirements", JobMatchScoreFindingSeverity.LIMITATION, "No structured job requirements could be evaluated safely, so no match score is available."))
    if match_result.unresolved_job_items:
        findings.append(_finding("unresolved_job_content_present", JobMatchScoreFindingSeverity.LIMITATION, "Some job-description content could not be structured and is not included in the match score."))
    if conflicting_duplicate_count:
        findings.append(_finding("conflicting_duplicate_match_results", JobMatchScoreFindingSeverity.LIMITATION, "Conflicting duplicate match results were excluded from the deterministic score."))
    return JobMatchScoreResult(
        policy=policy,
        match_score=_rounded_percent(weighted_earned, weighted_possible),
        evaluation_coverage=coverage,
        required_match_score=_score(required, policy),
        required_evaluation_coverage=_coverage(required),
        preferred_match_score=_score(preferred, policy),
        preferred_evaluation_coverage=_coverage(preferred),
        breakdown=breakdown,
        findings=tuple(findings),
    )

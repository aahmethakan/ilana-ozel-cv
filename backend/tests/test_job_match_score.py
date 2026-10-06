import inspect

import pytest
from pydantic import ValidationError

from app.domain.career import CareerFact, CareerProfile, FactSource, SourceType, VerificationStatus
from app.domain.job import (
    JobProfile,
    JobRequirement,
    RequirementCategory,
    RequirementExplicitness,
    RequirementImportance,
)
from app.services.job_analysis import UnresolvedJobItem
from app.services.job_match import JobMatchResult, RequirementMatchResult, RequirementMatchStatus, RequirementMatchType, match_job_to_profile
from app.services.job_match_score import calculate_job_match_score
from app.services.job_match_score import service as score_service


def requirement(
    text: str,
    importance: RequirementImportance = RequirementImportance.REQUIRED,
    category: RequirementCategory = RequirementCategory.SKILL,
) -> JobRequirement:
    return JobRequirement(
        requirement_id=f"job:{category.value}:{text}",
        category=category,
        text=text,
        importance=importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source_references=("job:line:1",),
        source_texts=(text,),
    )


def matched_result(
    requirement_item: JobRequirement,
    status: RequirementMatchStatus,
    reference: str = "cv:synthetic:1",
) -> RequirementMatchResult:
    return RequirementMatchResult(
        requirement=requirement_item,
        status=status,
        matched_evidence_references=(reference,) if status in {RequirementMatchStatus.MATCHED, RequirementMatchStatus.PARTIAL} else (),
        reason_code="synthetic",
        explanation="Synthetic evidence classification.",
    )


def score(*results: RequirementMatchResult, unresolved: tuple[UnresolvedJobItem, ...] = ()):
    return calculate_job_match_score(JobMatchResult(requirement_results=results, unresolved_job_items=unresolved))


@pytest.mark.parametrize(
    ("statuses", "expected_score"),
    [
        ((RequirementMatchStatus.MATCHED, RequirementMatchStatus.MATCHED), 100),
        ((RequirementMatchStatus.NOT_EVIDENCED, RequirementMatchStatus.NOT_EVIDENCED), 0),
        ((RequirementMatchStatus.MATCHED, RequirementMatchStatus.NOT_EVIDENCED), 50),
    ],
)
def test_basic_scores_are_reproducible(statuses: tuple[RequirementMatchStatus, ...], expected_score: int) -> None:
    results = tuple(matched_result(requirement(f"Synthetic {index}"), status) for index, status in enumerate(statuses))
    result = score(*results)

    assert result.match_score == expected_score
    assert result.evaluation_coverage == 100


def test_controlled_semantic_match_has_limited_score_impact() -> None:
    exact = matched_result(requirement("Excel"), RequirementMatchStatus.MATCHED)
    semantic = matched_result(requirement("Sales and Operations Planning"), RequirementMatchStatus.MATCHED).model_copy(
        update={"match_type": RequirementMatchType.CONTROLLED_SEMANTIC}
    )

    result = score(exact, semantic)

    assert result.match_score == 75


def test_manual_weighted_formula_uses_half_units_and_required_weight() -> None:
    required_matched = matched_result(requirement("SAP"), RequirementMatchStatus.MATCHED)
    required_missing = matched_result(requirement("PMP"), RequirementMatchStatus.NOT_EVIDENCED)
    preferred_partial = matched_result(requirement("English B2", RequirementImportance.PREFERRED), RequirementMatchStatus.PARTIAL)
    result = score(required_matched, required_missing, preferred_partial)

    assert result.breakdown.weighted_earned_units == 5
    assert result.breakdown.weighted_possible_units == 10
    assert result.match_score == 50


def test_unknown_importance_has_weight_one_and_never_enters_required_or_preferred_scores() -> None:
    unknown = matched_result(requirement("SAP", RequirementImportance.UNKNOWN), RequirementMatchStatus.MATCHED)
    required = matched_result(requirement("PMP"), RequirementMatchStatus.NOT_EVIDENCED)
    result = score(unknown, required)

    assert result.match_score == 33
    assert result.required_match_score == 0
    assert result.preferred_match_score is None
    assert result.breakdown.unknown_importance_count == 1
    assert result.breakdown.unknown_importance_evaluable_count == 1


def test_not_evaluable_is_excluded_from_score_but_reduces_coverage() -> None:
    results = (
        matched_result(requirement("SAP"), RequirementMatchStatus.MATCHED),
        matched_result(requirement("PMP"), RequirementMatchStatus.MATCHED),
        matched_result(requirement("Experience A"), RequirementMatchStatus.NOT_EVALUABLE),
        matched_result(requirement("Experience B"), RequirementMatchStatus.NOT_EVALUABLE),
        matched_result(requirement("Experience C"), RequirementMatchStatus.NOT_EVALUABLE),
    )
    result = score(*results)

    assert result.match_score == 100
    assert result.evaluation_coverage == 40
    assert result.breakdown.not_evaluable_count == 3
    assert any(item.code == "coverage_incomplete" for item in result.findings)


def test_half_up_rounding_uses_integer_units_at_an_exact_half_boundary() -> None:
    required_matched = matched_result(requirement("SAP"), RequirementMatchStatus.MATCHED)
    preferred_partial = matched_result(requirement("English B2", RequirementImportance.PREFERRED), RequirementMatchStatus.PARTIAL)
    preferred_missing = matched_result(requirement("PMP", RequirementImportance.PREFERRED), RequirementMatchStatus.NOT_EVIDENCED)
    result = score(required_matched, preferred_partial, preferred_missing)

    assert result.breakdown.weighted_earned_units == 5
    assert result.breakdown.weighted_possible_units == 8
    assert result.match_score == 63


def test_zero_evaluable_and_zero_structured_cases_are_unavailable_not_zero() -> None:
    not_evaluable = score(matched_result(requirement("Experience"), RequirementMatchStatus.NOT_EVALUABLE))
    empty = score()

    assert not_evaluable.match_score is None
    assert not_evaluable.evaluation_coverage == 0
    assert any(item.code == "no_evaluable_requirements" for item in not_evaluable.findings)
    assert empty.match_score is None and empty.evaluation_coverage is None
    assert any(item.code == "no_structured_requirements" for item in empty.findings)


def test_zero_structured_requirements_with_unresolved_content_preserves_both_limitations() -> None:
    unresolved = UnresolvedJobItem(source_reference="job:line:7", original_text="Synthetic prose", reason_code="unknown_section")
    result = score(unresolved=(unresolved,))

    assert result.match_score is None and result.evaluation_coverage is None
    assert {item.code for item in result.findings} == {"no_structured_requirements", "unresolved_job_content_present"}


def test_required_and_preferred_scores_and_coverages_are_independent() -> None:
    required_match = matched_result(requirement("SAP"), RequirementMatchStatus.MATCHED)
    required_unevaluable = matched_result(requirement("Experience", RequirementImportance.REQUIRED), RequirementMatchStatus.NOT_EVALUABLE)
    preferred_missing = matched_result(requirement("PMP", RequirementImportance.PREFERRED), RequirementMatchStatus.NOT_EVIDENCED)
    result = score(required_match, required_unevaluable, preferred_missing)

    assert result.required_match_score == 100
    assert result.required_evaluation_coverage == 50
    assert result.preferred_match_score == 0
    assert result.preferred_evaluation_coverage == 100


def test_preferred_full_score_with_incomplete_preferred_coverage_is_visible() -> None:
    matched = matched_result(requirement("SAP", RequirementImportance.PREFERRED), RequirementMatchStatus.MATCHED)
    unevaluable = matched_result(requirement("Experience", RequirementImportance.PREFERRED), RequirementMatchStatus.NOT_EVALUABLE)
    result = score(matched, unevaluable)

    assert result.preferred_match_score == 100
    assert result.preferred_evaluation_coverage == 50
    assert any(item.code == "coverage_incomplete" for item in result.findings)


def test_unresolved_job_items_are_reported_without_changing_score() -> None:
    unresolved = UnresolvedJobItem(source_reference="job:line:7", original_text="Synthetic prose", reason_code="unknown_section")
    without_unresolved = score(matched_result(requirement("SAP"), RequirementMatchStatus.MATCHED))
    with_unresolved = score(matched_result(requirement("SAP"), RequirementMatchStatus.MATCHED), unresolved=(unresolved,))

    assert with_unresolved.match_score == without_unresolved.match_score == 100
    assert with_unresolved.evaluation_coverage == 100
    assert with_unresolved.breakdown.unresolved_job_item_count == 1
    assert any(item.code == "unresolved_job_content_present" for item in with_unresolved.findings)


def test_duplicate_results_do_not_inflate_and_conflicting_statuses_are_excluded() -> None:
    item = requirement("SAP")
    duplicate = score(matched_result(item, RequirementMatchStatus.MATCHED), matched_result(item.model_copy(update={"source_references": ("job:line:2",)}), RequirementMatchStatus.MATCHED))
    conflict = score(matched_result(item, RequirementMatchStatus.MATCHED), matched_result(item, RequirementMatchStatus.NOT_EVIDENCED))

    assert duplicate.match_score == 100 and duplicate.breakdown.duplicate_result_count == 1
    assert conflict.match_score is None and conflict.evaluation_coverage == 0
    assert conflict.breakdown.conflicting_duplicate_result_count == 1
    assert any(item.code == "conflicting_duplicate_match_results" for item in conflict.findings)


def test_different_stable_requirement_ids_are_not_semantically_deduplicated() -> None:
    sap = requirement("SAP")
    sap_erp = requirement("SAP ERP")
    result = score(matched_result(sap, RequirementMatchStatus.MATCHED), matched_result(sap_erp, RequirementMatchStatus.NOT_EVIDENCED))

    assert result.breakdown.structured_requirement_count == 2
    assert result.match_score == 50


def test_duplicate_identity_with_conflicting_importance_remains_unknown() -> None:
    required = requirement("SAP", RequirementImportance.REQUIRED)
    preferred = required.model_copy(update={"importance": RequirementImportance.PREFERRED, "source_references": ("job:line:2",)})
    result = score(matched_result(required, RequirementMatchStatus.MATCHED), matched_result(preferred, RequirementMatchStatus.MATCHED))

    assert result.breakdown.structured_requirement_count == 1
    assert result.breakdown.unknown_importance_count == 1
    assert result.required_match_score is None and result.preferred_match_score is None


def test_score_uses_existing_matcher_statuses_without_rematching() -> None:
    sap = requirement("SAP")
    pmp = requirement("PMP")
    english = requirement("English B2", RequirementImportance.PREFERRED, RequirementCategory.LANGUAGE)
    experience = requirement("3 years experience", RequirementImportance.REQUIRED, RequirementCategory.EXPERIENCE)
    fact = CareerFact(
        statement="SAP",
        skills=("SAP",),
        verification_status=VerificationStatus.VERIFIED,
        source=FactSource(source_type=SourceType.MASTER_CV, reference="cv:skill:1", original_text="SAP"),
    )
    match_result = match_job_to_profile(JobProfile(requirements=(sap, pmp, english, experience)), CareerProfile(skills=(fact,)))
    result = calculate_job_match_score(match_result)

    assert [item.status for item in match_result.requirement_results] == [RequirementMatchStatus.MATCHED, RequirementMatchStatus.NOT_EVIDENCED, RequirementMatchStatus.NOT_EVALUABLE, RequirementMatchStatus.NOT_EVALUABLE]
    assert result.match_score == 50
    assert result.evaluation_coverage == 50
    assert result.breakdown.weighted_earned_units == 4
    assert result.breakdown.weighted_possible_units == 8


def test_score_result_is_immutable_deterministic_and_has_no_ai_or_matcher_dependency() -> None:
    input_result = JobMatchResult(requirement_results=(matched_result(requirement("SAP"), RequirementMatchStatus.MATCHED),))
    first = calculate_job_match_score(input_result)
    second = calculate_job_match_score(input_result)

    assert first == second
    with pytest.raises(ValidationError):
        first.match_score = 0
    source_text = inspect.getsource(score_service)
    assert "CareerProfile" not in source_text
    assert "match_job_to_profile" not in source_text
    assert "app.ai" not in source_text and "embedding" not in source_text

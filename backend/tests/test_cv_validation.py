from app.services.cv_validation.consistency_validator import validate_consistency
from app.services.cv_validation.fact_validator import validate_facts
from app.services.cv_validation.format_validator import validate_format
from app.services.cv_validation.language_validator import validate_language
from app.services.draft_review import reviewed_draft
from app.services.public_cv_projection import build_public_cv_projection
from app.services.generation_orchestration import generate_deterministic_cv
from app.services.generation_strategy import build_generation_plan
from app.domain.career import CareerProfile
from app.services.cv_validation.schemas import ValidationSeverity

from tests.test_work_fact_association_claim_validation import associated_context


def _authoritative_values():
    context = associated_context()
    draft = generate_deterministic_cv(context, build_generation_plan(context))
    reviewed = reviewed_draft(draft)
    projection = build_public_cv_projection(profile=CareerProfile(), reviewed_draft=reviewed)
    return context, draft, reviewed, projection


def test_fact_validator_blocks_tampered_skill_metric_technology_seniority_and_leadership() -> None:
    context, draft, _, _ = _authoritative_values()
    for injected in ("25", "Siemens", "Senior Engineer", "Led a team", "Oracle"):
        tampered_claim = draft.work_entries[0].fact_claims[0].model_copy(update={"text": injected})
        tampered_entry = draft.work_entries[0].model_copy(update={"fact_claims": (tampered_claim,)})
        tampered = draft.model_copy(update={"work_entries": (tampered_entry,)})
        issues = validate_facts(draft=tampered, reviewed=reviewed_draft(tampered), context=context, decisions={}, rewrites={})
        assert any(issue.code == "UNSUPPORTED_CLAIM" and issue.severity is ValidationSeverity.BLOCK for issue in issues)


def test_projection_validators_detect_duplicate_empty_and_language_artifacts_without_mutation() -> None:
    _, _, reviewed, projection = _authoritative_values()
    duplicate = reviewed.review.model_copy(update={"skills": ()})
    # Add duplicate synthetic public values only through model_copy: validation
    # must flag the projection and never modify its immutable source object.
    claim = reviewed.review.work_entries[0].claims[0]
    duplicate = duplicate.model_copy(update={"skills": (claim, claim)})
    duplicated_projection = projection.model_copy(update={"reviewed_draft": reviewed.model_copy(update={"review": duplicate})})
    assert any(issue.code == "DUPLICATE_SKILL" for issue in validate_consistency(duplicated_projection))
    broken_claim = claim.model_copy(update={"text": "  Engineer Engineer!!! �  "})
    broken_review = duplicate.model_copy(update={"work_entries": (duplicate.work_entries[0].model_copy(update={"claims": (broken_claim,)}),)})
    broken_projection = projection.model_copy(update={"reviewed_draft": reviewed.model_copy(update={"review": broken_review})})
    assert any(issue.severity is ValidationSeverity.BLOCK for issue in validate_format(broken_projection)) is False
    language = validate_language(broken_projection)
    assert {issue.code for issue in language} >= {"SUSPICIOUS_ENCODING", "REPEATED_WORD", "BROKEN_WHITESPACE_OR_PUNCTUATION"}
    assert projection.reviewed_draft == reviewed

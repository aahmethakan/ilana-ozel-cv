from app.ai.career import AIConfidence, AIInterpretationResponse, AIProposedCandidate, CandidateType, create_career_fact_candidates
from app.confirmation.career import ConfirmationAction, resolve_candidate
from app.confirmation.career.service import candidate_id
from app.domain.career import SourceType, VerificationStatus
from tests.test_ai_career_foundation import source_document


def candidate(source: str, proposed: str, candidate_type: CandidateType = CandidateType.SKILL):
    return create_career_fact_candidates(source_document(source), AIInterpretationResponse(candidates=(AIProposedCandidate(candidate_type=candidate_type, proposed_statement=proposed, evidence_references=("page:1:block:1",), confidence=AIConfidence.HIGH),))).candidates[0]


def test_accept_promotes_simple_candidate_as_user_provided_with_audit_provenance() -> None:
    original = candidate("Python", "Python")
    result = resolve_candidate(original, ConfirmationAction.ACCEPT)

    assert result.promoted_fact is not None and result.promoted_fact.is_claim_usable
    assert result.promoted_fact.verification_status is VerificationStatus.USER_PROVIDED
    assert result.promoted_fact.source.source_type is SourceType.USER_INPUT
    assert result.audit.evidence_references == ("page:1:block:1",)
    assert original.verification_status is VerificationStatus.INFERRED_UNVERIFIED


def test_reject_creates_no_fact_and_is_explicit() -> None:
    result = resolve_candidate(candidate("Python", "Python"), ConfirmationAction.REJECT)
    assert result.promoted_fact is None and result.is_rejected is True


def test_correct_requires_nonblank_and_preserves_trimmed_unicode_user_input() -> None:
    original = candidate("Excel", "Advanced Excel")
    blocked = resolve_candidate(original, ConfirmationAction.CORRECT, correction=" ")
    corrected = resolve_candidate(original, ConfirmationAction.CORRECT, correction="  İleri Excel  ")
    assert blocked.issue_codes == ("missing_user_correction",)
    assert corrected.promoted_fact is not None and corrected.promoted_fact.statement == "İleri Excel"
    assert corrected.promoted_fact.source.source_type is SourceType.USER_INPUT
    assert corrected.audit.original_proposed_statement == "Advanced Excel"


def test_accept_is_blocked_for_all_inflation_categories_but_correction_is_allowed() -> None:
    cases = [("SAP", "SAP ERP"), ("Excel", "Advanced Excel"), ("Improved process", "Improved process by 25%"), ("Worked on production", "Led production team")]
    for source, proposed in cases:
        original = candidate(source, proposed)
        assert resolve_candidate(original, ConfirmationAction.ACCEPT).promoted_fact is None
    corrected = resolve_candidate(candidate("Excel", "Advanced Excel"), ConfirmationAction.CORRECT, correction="Advanced Excel")
    assert corrected.promoted_fact is not None and corrected.promoted_fact.is_claim_usable


def test_low_confidence_nonblocking_candidate_can_be_user_confirmed_and_models_serialize() -> None:
    proposed = AIProposedCandidate(candidate_type=CandidateType.SKILL, proposed_statement="Python", evidence_references=("page:1:block:1",), confidence=AIConfidence.LOW)
    original = create_career_fact_candidates(source_document("Python"), AIInterpretationResponse(candidates=(proposed,))).candidates[0]
    result = resolve_candidate(original, ConfirmationAction.ACCEPT)
    assert result.model_dump(mode="json")["promoted_fact"]["source"]["source_type"] == "user_input"


def test_candidate_identity_is_deterministic_and_changes_with_candidate_content() -> None:
    first = candidate("Python", "Python")
    equivalent = candidate("Python", "Python")
    different = candidate("Python", "Python programming")

    assert candidate_id(first) == candidate_id(equivalent)
    assert len(candidate_id(first)) == 64
    assert candidate_id(first) != candidate_id(different)


def test_already_resolved_and_unsafe_structured_types_are_not_promoted() -> None:
    original = candidate("Python", "Python")
    duplicate = resolve_candidate(
        original,
        ConfirmationAction.ACCEPT,
        resolved_candidate_ids=frozenset({candidate_id(original)}),
    )
    assert duplicate.promoted_fact is None and duplicate.issue_codes == ("already_resolved",)

    for candidate_type in (CandidateType.WORK_EXPERIENCE, CandidateType.EDUCATION, CandidateType.CONTACT):
        unsafe = candidate("Example", "Example", candidate_type)
        assert resolve_candidate(unsafe, ConfirmationAction.ACCEPT).promoted_fact is None

from app.ai.career import AIConfidence, AIInterpretationResponse, AIProposedCandidate, CandidateType, MockAIProvider
from app.domain.career import VerificationStatus
from app.domain.document import BlockType, SectionType
from app.services.career_assistance import assist_career_extraction
from tests.test_career_extraction import document_with_sections


class RecordingProvider:
    def __init__(self, response: AIInterpretationResponse) -> None:
        self.response = response
        self.requests = []

    def interpret_career_evidence(self, request):
        self.requests.append(request)
        return self.response


class FailingProvider:
    def interpret_career_evidence(self, request):
        raise RuntimeError("synthetic provider failure")


def source_document():
    return document_with_sections(
        [
            (SectionType.SKILLS, [("- Python", BlockType.BULLET)]),
            (SectionType.EXPERIENCE, [("Production Engineer", BlockType.PARAGRAPH), ("Example Manufacturing", BlockType.PARAGRAPH), ("2022 - 2024", BlockType.PARAGRAPH)]),
        ]
    )


def work_response() -> AIInterpretationResponse:
    return AIInterpretationResponse(candidates=(AIProposedCandidate(candidate_type=CandidateType.WORK_EXPERIENCE, proposed_statement="Production Engineer at Example Manufacturing", evidence_references=("page:1:block:3", "page:1:block:4", "page:1:block:5"), confidence=AIConfidence.HIGH),))


def test_orchestration_preserves_deterministic_profile_and_sends_only_unresolved_evidence() -> None:
    provider = RecordingProvider(work_response())
    result = assist_career_extraction(source_document(), provider)

    assert [fact.statement for fact in result.deterministic_profile.skills] == ["Python"]
    assert all("Python" not in item.original_text for request in provider.requests for item in request.evidence)
    assert result.ai_candidates[0].evidence_references == ("page:1:block:3", "page:1:block:4", "page:1:block:5")
    assert result.ai_candidates[0].verification_status is VerificationStatus.INFERRED_UNVERIFIED
    assert result.ai_candidates[0].is_claim_usable is False
    assert result.ai_candidates[0].requires_user_confirmation is True
    assert len(result.ai_candidates) == 1


def test_empty_provider_response_leaves_evidence_unresolved() -> None:
    result = assist_career_extraction(source_document(), MockAIProvider(AIInterpretationResponse()))
    assert result.ai_candidates == ()
    assert result.remaining_unresolved_evidence == result.deterministic_unresolved_evidence
    assert {issue.issue_code for issue in result.processing_issues} == {"no_candidate_returned"}


def test_provider_failure_isolated_and_keeps_deterministic_profile_and_evidence() -> None:
    result = assist_career_extraction(source_document(), FailingProvider())
    assert [fact.statement for fact in result.deterministic_profile.skills] == ["Python"]
    assert result.remaining_unresolved_evidence == result.deterministic_unresolved_evidence
    assert {issue.issue_code for issue in result.processing_issues} == {"provider_error"}


def test_invalid_ai_reference_is_rejected_and_result_serializes() -> None:
    response = AIInterpretationResponse(candidates=(AIProposedCandidate(candidate_type=CandidateType.SKILL, proposed_statement="Python", evidence_references=("page:1:block:99",), confidence=AIConfidence.HIGH),))
    result = assist_career_extraction(source_document(), MockAIProvider(response))
    assert result.rejected_ai_proposals[0].reason == "unknown_evidence_reference"
    assert result.model_dump(mode="json")["deterministic_profile"]["skills"][0]["statement"] == "Python"

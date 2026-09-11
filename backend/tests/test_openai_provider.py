import json

import pytest

from app.ai.career import AIConfidence, AIInterpretationRequest, AIProposedCandidate, CandidateType, EvidenceContext, create_career_fact_candidates
from app.ai.providers.openai_provider import (
    OpenAIConfigurationError,
    OpenAIProvider,
    OpenAIProviderSettings,
    OpenAIRequestError,
    OpenAIResponseError,
)
from tests.test_ai_career_foundation import request_for_document, source_document


class FakeResponses:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


class FakeResponse:
    def __init__(self, output_parsed) -> None:
        self.output_parsed = output_parsed


def request() -> AIInterpretationRequest:
    return AIInterpretationRequest(
        evidence=(EvidenceContext(reference="page:1:block:1", original_text="Production Engineer"),),
        target_category=CandidateType.WORK_EXPERIENCE,
    )


def provider(responses: FakeResponses) -> OpenAIProvider:
    return OpenAIProvider(OpenAIProviderSettings(api_key="test-key", model="test-model", timeout_seconds=12), FakeClient(responses))


def test_missing_configuration_fails_without_exposing_a_key() -> None:
    with pytest.raises(OpenAIConfigurationError, match="not configured"):
        OpenAIProvider(OpenAIProviderSettings(api_key=None))


def test_provider_maps_only_structured_request_evidence_to_payload() -> None:
    responses = FakeResponses(FakeResponse({"candidates": []}))
    assert provider(responses).interpret_career_evidence(request()).candidates == ()

    payload = json.loads(responses.kwargs["input"])
    assert payload["evidence"] == [{"reference": "page:1:block:1", "original_text": "Production Engineer", "section_type": None}]
    assert responses.kwargs["model"] == "test-model"
    assert "Use only supplied evidence" in responses.kwargs["instructions"]


def test_multiple_structured_proposals_preserve_references_confidence_and_rationale() -> None:
    parsed = {"candidates": [
        {"candidate_type": "skill", "proposed_statement": "Excel", "evidence_references": ["page:1:block:1"], "confidence": "low", "rationale": "The source names Excel."},
        {"candidate_type": "work_experience", "proposed_statement": "Production Engineer", "evidence_references": ["page:1:block:1", "page:1:block:2"], "confidence": "high"},
    ]}
    response = provider(FakeResponses(FakeResponse(parsed))).interpret_career_evidence(request())
    assert response.candidates[0].confidence is AIConfidence.LOW
    assert response.candidates[0].rationale == "The source names Excel."
    assert response.candidates[1].evidence_references == ("page:1:block:1", "page:1:block:2")


def test_invalid_or_failed_provider_response_raises_safe_typed_error() -> None:
    with pytest.raises(OpenAIResponseError, match="invalid structured response"):
        provider(FakeResponses(FakeResponse(None))).interpret_career_evidence(request())
    with pytest.raises(OpenAIRequestError, match="request failed") as error:
        provider(FakeResponses(error=RuntimeError("secret transport detail"))).interpret_career_evidence(request())
    assert "secret" not in str(error.value)


def test_existing_candidate_validation_remains_authoritative() -> None:
    response = provider(FakeResponses(FakeResponse({"candidates": [{"candidate_type": "skill", "proposed_statement": "Advanced Excel", "evidence_references": ["page:1:block:1"], "confidence": "high"}]}))).interpret_career_evidence(request())
    document = source_document("Excel")
    candidate = create_career_fact_candidates(document, response, request_for_document(document)).candidates[0]
    assert "unsupported_strengthening" in candidate.issue_codes

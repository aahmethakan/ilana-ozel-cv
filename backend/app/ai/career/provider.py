from typing import Protocol

from app.ai.career.schemas import AIInterpretationRequest, AIInterpretationResponse


class AIProvider(Protocol):
    """A model-independent provider boundary with no network assumptions."""

    def interpret_career_evidence(self, request: AIInterpretationRequest) -> AIInterpretationResponse: ...


class MockAIProvider:
    """Deterministic provider used only for tests and local safety demonstrations."""

    def __init__(self, response: AIInterpretationResponse) -> None:
        self._response = response

    def interpret_career_evidence(self, request: AIInterpretationRequest) -> AIInterpretationResponse:
        _ = request
        return self._response

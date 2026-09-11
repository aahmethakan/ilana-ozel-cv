from typing import Protocol

from openai import OpenAI
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.career.schemas import AIInterpretationRequest, AIInterpretationResponse

_SYSTEM_INSTRUCTIONS = """Interpret only the supplied CV evidence. Return structured candidate proposals only.
Use only supplied evidence references. Do not invent facts, metrics, seniority, leadership, or stronger wording.
If uncertain, return no proposal. Include only concise user-safe rationales; never return hidden reasoning or CV prose."""


class OpenAIProviderError(Exception):
    """Safe base error for the OpenAI provider boundary."""


class OpenAIConfigurationError(OpenAIProviderError):
    pass


class OpenAIRequestError(OpenAIProviderError):
    pass


class OpenAIResponseError(OpenAIProviderError):
    pass


class OpenAIClient(Protocol):
    class responses(Protocol):
        @staticmethod
        def parse(**kwargs: object) -> object: ...


class OpenAIProviderSettings(BaseSettings):
    """Environment-only provider settings; no secret is stored in application models."""

    api_key: str | None = None
    model: str = "gpt-4o-mini"
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    model_config = SettingsConfigDict(env_prefix="ILANA_OPENAI_", extra="ignore")


class OpenAIProvider:
    """OpenAI structured-output adapter; candidate validation remains outside this provider."""

    def __init__(self, settings: OpenAIProviderSettings | None = None, client: OpenAIClient | None = None) -> None:
        self._settings = settings or OpenAIProviderSettings()
        if not self._settings.api_key:
            raise OpenAIConfigurationError("OpenAI provider is not configured.")
        self._client = client or OpenAI(
            api_key=self._settings.api_key,
            timeout=self._settings.timeout_seconds,
            max_retries=0,
        )

    def interpret_career_evidence(self, request: AIInterpretationRequest) -> AIInterpretationResponse:
        try:
            response = self._client.responses.parse(
                model=self._settings.model,
                instructions=_SYSTEM_INSTRUCTIONS,
                input=request.model_dump_json(),
                text_format=AIInterpretationResponse,
            )
        except Exception as error:
            raise OpenAIRequestError("OpenAI interpretation request failed.") from error
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise OpenAIResponseError("OpenAI returned an invalid structured response.")
        try:
            return AIInterpretationResponse.model_validate(parsed)
        except Exception as error:
            raise OpenAIResponseError("OpenAI returned an invalid structured response.") from error

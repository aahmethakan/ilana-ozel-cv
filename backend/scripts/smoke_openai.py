"""Optional live OpenAI smoke check. Never run this from pytest."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.career.schemas import AIInterpretationRequest, EvidenceContext
from app.ai.providers import OpenAIConfigurationError, OpenAIProvider, OpenAIProviderError
from app.services.controlled_rewrite import controlled_rewrite


def main() -> int:
    if not os.getenv("ILANA_OPENAI_API_KEY"):
        print("SKIPPED - OPENAI_API_KEY not configured")
        return 0
    try:
        provider = OpenAIProvider()
        response = provider.interpret_career_evidence(AIInterpretationRequest(
            evidence=(EvidenceContext(reference="smoke:user-answer", original_text="I used Siemens S7-1200 during commissioning."),),
        ))
        # Structured parsing must succeed, but the response remains untrusted.
        assert all(not candidate.is_claim_usable for candidate in response.candidates)
        rewrite = controlled_rewrite(provider, original="Installed and commissioned production machinery.", mode="smoke")
        print(f"PASS - structured candidates={len(response.candidates)} rewrite={rewrite.final_status.value}")
        return 0
    except OpenAIConfigurationError:
        print("SKIPPED - OPENAI_API_KEY not configured")
        return 0
    except OpenAIProviderError as error:
        print(f"FAILED - provider error category: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

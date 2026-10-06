from app.services.controlled_rewrite import RewriteProposal, RewriteFinalStatus
from app.services.cover_letter.rewrite.service import enhance_cover_letter_wording


class Provider:
    def __init__(self, text: str | Exception) -> None:
        self.text = text

    def rewrite_claim(self, *, source_text: str, mode: str) -> RewriteProposal:
        if isinstance(self.text, Exception):
            raise self.text
        return RewriteProposal(rewritten_text=self.text)


def test_cover_letter_safe_wording_is_accepted_without_changing_source_identity() -> None:
    result = enhance_cover_letter_wording(
        item_id="cover-item:1", original_text="Performed production operations", category="EXPERIENCE",
        provider=Provider("Performed daily production operations"),
    )
    assert result.final_status is RewriteFinalStatus.ACCEPTED
    assert result.rewritten_text == "Performed daily production operations"


def test_cover_letter_unsafe_numbers_metrics_technology_company_skill_and_scope_fall_back() -> None:
    original = "Performed machine commissioning"
    for unsafe in (
        "Performed commissioning of 25 machines",
        "Performed commissioning with 20% improvement",
        "Performed Siemens PLC commissioning",
        "Performed commissioning for Siemens",
        "Performed commissioning and Python automation",
        "Led the commissioning team",
        "Managed the international engineering organization",
    ):
        result = enhance_cover_letter_wording(item_id="cover-item:1", original_text=original, category="EXPERIENCE", provider=Provider(unsafe))
        assert result.final_status is RewriteFinalStatus.REJECTED
        assert result.rewritten_text == original


def test_cover_letter_provider_failure_and_empty_output_preserve_original() -> None:
    original = "SAP"
    for output in (RuntimeError("unavailable"), ""):
        result = enhance_cover_letter_wording(item_id="cover-item:1", original_text=original, category="SKILL", provider=Provider(output))
        assert result.final_status is RewriteFinalStatus.REJECTED
        assert result.rewritten_text == original

import pytest

from app.services.controlled_rewrite import ControlledRewriteError, RewriteProposal, assess_quality, controlled_rewrite, validate_rewrite


class Provider:
    def __init__(self, text: str): self.text = text
    def rewrite_claim(self, *, source_text: str, mode: str) -> RewriteProposal:
        assert mode == "general"
        return RewriteProposal(rewritten_text=self.text)


def test_controlled_rewrite_accepts_safe_wording_and_rejects_factual_additions() -> None:
    assert controlled_rewrite(Provider("Installed and commissioned production machinery."), original="Installed and commissioned production machines.", mode="general").final_status == "accepted"
    for text in ("Used SAP ERP and Python.", "Reduced downtime by 25%.", "Led a team to install machines.", "Worked with Siemens PLC systems."):
        source = "Used SAP ERP." if "SAP" in text else "Reduced downtime by 15%." if "25" in text else "Installed machines." if "team" in text else "Worked with PLC systems."
        with pytest.raises(ControlledRewriteError):
            validate_rewrite(original=source, rewritten=text)


def test_rewrite_quality_distinguishes_improved_unchanged_and_low_value_wording() -> None:
    assert assess_quality(original="Used SAP ERP.", rewritten="Used SAP ERP.") == "unchanged"
    assert assess_quality(original="Installed machines.", rewritten="Performed installation of machines.") == "improved"
    assert assess_quality(original="Used SAP.", rewritten="I used SAP in a highly dynamic and very results-driven environment.") == "not_improved"

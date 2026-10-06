import pytest

from app.domain.document import ParserConfidence
from app.domain.document.continuation import create_company_continuation_evidence


def test_company_continuation_evidence_is_deterministic_and_unverified() -> None:
    kwargs = dict(proposed_company="Example Retail", previous_company_reference="page:1:block:2", current_role_references=("page:1:block:6", "page:1:block:7"), section_reference="page:1:block:0", confidence=ParserConfidence.HIGH)
    first = create_company_continuation_evidence(**kwargs)
    second = create_company_continuation_evidence(**kwargs)

    assert first.candidate_id == second.candidate_id
    assert first.verification_status == "inferred_unverified"
    assert "Example Retail" in first.canonical_payload()["proposed_company"]


def test_company_continuation_evidence_rejects_missing_role_lineage() -> None:
    with pytest.raises(ValueError):
        create_company_continuation_evidence(proposed_company="Example Retail", previous_company_reference="page:1:block:2", current_role_references=(), section_reference="page:1:block:0", confidence=ParserConfidence.HIGH)

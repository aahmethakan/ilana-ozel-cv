import pytest
from pydantic import ValidationError

from app.ai.career import (
    AIConfidence,
    AIInterpretationRequest,
    AIInterpretationResponse,
    AIProposedCandidate,
    CandidateType,
    EvidenceContext,
    MockAIProvider,
    create_career_fact_candidates,
)
from app.ai.career.validation import can_auto_promote
from app.ai.career.validation import CareerFactCandidate
from app.domain.career import VerificationStatus
from app.domain.document import CVDocument, DocumentBlock, DocumentFormat, DocumentPage, DocumentSource, BlockType, SourceLocation


def source_document(*texts: str) -> CVDocument:
    blocks = tuple(
        DocumentBlock(raw_text=text, block_type=BlockType.PARAGRAPH, location=SourceLocation(page_number=1, block_index=index))
        for index, text in enumerate(texts, start=1)
    )
    return CVDocument(
        source=DocumentSource(filename="synthetic.pdf", document_format=DocumentFormat.PDF, page_count=1),
        blocks=blocks,
        pages=(DocumentPage(page_number=1, block_references=tuple(block.stable_reference for block in blocks)),),
    )


def request_for_document(document: CVDocument) -> AIInterpretationRequest:
    return AIInterpretationRequest(
        evidence=tuple(
            EvidenceContext(reference=block.stable_reference, original_text=block.raw_text)
            for block in document.blocks
        )
    )


def proposal(statement: str, references: tuple[str, ...], candidate_type: CandidateType = CandidateType.SKILL, **kwargs: object) -> AIProposedCandidate:
    return AIProposedCandidate(
        candidate_type=candidate_type,
        proposed_statement=statement,
        evidence_references=references,
        confidence=AIConfidence.HIGH,
        rationale="Source wording was supplied for review.",
        **kwargs,
    )


def test_structured_request_and_response_are_json_serializable() -> None:
    request = AIInterpretationRequest(
        evidence=(EvidenceContext(reference="page:1:block:1", original_text="Excel"),),
        target_category=CandidateType.SKILL,
    )
    response = AIInterpretationResponse(candidates=(proposal("Excel", ("page:1:block:1",)),))

    assert request.model_dump(mode="json")["evidence"][0]["reference"] == "page:1:block:1"
    assert response.model_dump(mode="json")["candidates"][0]["confidence"] == "high"


def test_proposal_requires_nonblank_statement_and_evidence_reference() -> None:
    with pytest.raises(ValidationError):
        proposal(" ", ("page:1:block:1",))
    with pytest.raises(ValidationError):
        proposal("Excel", ())
    with pytest.raises(ValidationError):
        proposal("Excel", ("page:1:block:1",), requires_user_confirmation=False)


def test_candidate_model_rejects_blank_statement_and_reference() -> None:
    with pytest.raises(ValidationError):
        CareerFactCandidate(
            candidate_type=CandidateType.SKILL,
            proposed_statement=" ",
            evidence_references=("page:1:block:1",),
            confidence=AIConfidence.LOW,
        )


def test_candidate_model_cannot_be_marked_verified_or_confirmation_free() -> None:
    with pytest.raises(ValidationError):
        CareerFactCandidate(
            candidate_type=CandidateType.SKILL,
            proposed_statement="Excel",
            evidence_references=("page:1:block:1",),
            confidence=AIConfidence.HIGH,
            verification_status=VerificationStatus.VERIFIED,
        )
    with pytest.raises(ValidationError):
        CareerFactCandidate(
            candidate_type=CandidateType.SKILL,
            proposed_statement="Excel",
            evidence_references=("page:1:block:1",),
            confidence=AIConfidence.HIGH,
            requires_user_confirmation=False,
        )
    with pytest.raises(ValidationError):
        CareerFactCandidate(
            candidate_type=CandidateType.SKILL,
            proposed_statement="Excel",
            evidence_references=(" ",),
            confidence=AIConfidence.LOW,
        )


def test_dangling_evidence_reference_is_rejected() -> None:
    document = source_document("Excel")
    result = create_career_fact_candidates(
        document,
        AIInterpretationResponse(candidates=(proposal("Excel", ("page:1:block:99",)),)),
        AIInterpretationRequest(
            evidence=(EvidenceContext(reference="page:1:block:99", original_text="Excel"),)
        ),
    )

    assert result.candidates == ()
    assert result.rejected_proposals[0].reason == "unknown_evidence_reference"


def test_ai_candidate_is_always_unverified_and_not_usable_even_at_high_confidence() -> None:
    document = source_document("Excel")
    result = create_career_fact_candidates(
        document,
        AIInterpretationResponse(candidates=(proposal("Excel", ("page:1:block:1",)),)),
        request_for_document(document),
    )

    candidate = result.candidates[0]
    assert candidate.confidence is AIConfidence.HIGH
    assert candidate.verification_status is VerificationStatus.INFERRED_UNVERIFIED
    assert candidate.requires_user_confirmation is True
    assert candidate.is_claim_usable is False
    assert can_auto_promote(candidate) is False


@pytest.mark.parametrize(
    ("source", "proposed", "issue"),
    [
        ("SAP", "SAP ERP", "unsupported_strengthening"),
        ("Excel", "Advanced Excel", "unsupported_strengthening"),
        ("Engineer", "Senior Engineer", "unsupported_seniority"),
        ("Improved process", "Improved process by 25%", "unsupported_metric"),
        ("Worked on production", "Led production team", "unsupported_responsibility"),
    ],
)
def test_obvious_unsupported_strengthening_is_flagged(source: str, proposed: str, issue: str) -> None:
    document = source_document(source)
    result = create_career_fact_candidates(
        document,
        AIInterpretationResponse(candidates=(proposal(proposed, ("page:1:block:1",)),)),
        request_for_document(document),
    )

    candidate = result.candidates[0]
    assert issue in candidate.issue_codes
    assert candidate.is_claim_usable is False


def test_candidate_preserves_multiple_work_experience_evidence_references() -> None:
    document = source_document("Production Engineer", "Example Manufacturing", "2022 - 2024")
    response = AIInterpretationResponse(
        candidates=(
            proposal(
                "Production Engineer at Example Manufacturing",
                ("page:1:block:1", "page:1:block:2", "page:1:block:3"),
                candidate_type=CandidateType.WORK_EXPERIENCE,
                proposed_fields=(
                    {"name": "title", "value": "Production Engineer"},
                    {"name": "company", "value": "Example Manufacturing"},
                    {"name": "dates", "value": "2022 - 2024"},
                ),
            ),
        )
    )

    candidate = create_career_fact_candidates(document, response, request_for_document(document)).candidates[0]

    assert candidate.evidence_references == ("page:1:block:1", "page:1:block:2", "page:1:block:3")
    assert candidate.verification_status is VerificationStatus.INFERRED_UNVERIFIED
    assert candidate.requires_user_confirmation is True


def test_education_candidate_remains_unverified() -> None:
    document = source_document("Example University", "Engineering")
    candidate = create_career_fact_candidates(
        document,
        AIInterpretationResponse(candidates=(proposal("Engineering at Example University", ("page:1:block:1", "page:1:block:2"), CandidateType.EDUCATION),)),
        request_for_document(document),
    ).candidates[0]

    assert candidate.verification_status is VerificationStatus.INFERRED_UNVERIFIED
    assert candidate.is_claim_usable is False


def test_request_evidence_boundary_rejects_a_document_reference_not_sent_to_ai() -> None:
    document = source_document("Production Engineer", "Example Manufacturing", "2022 - 2024", "Unrelated block")
    request = AIInterpretationRequest(
        evidence=tuple(
            EvidenceContext(reference=block.stable_reference, original_text=block.raw_text)
            for block in document.blocks[:3]
        ),
        target_category=CandidateType.WORK_EXPERIENCE,
    )
    response = AIInterpretationResponse(
        candidates=(proposal("Production Engineer", ("page:1:block:4",), CandidateType.WORK_EXPERIENCE),)
    )

    result = create_career_fact_candidates(document, response, request)

    assert result.candidates == ()
    assert result.rejected_proposals[0].reason == "unknown_request_evidence_reference"


def test_mock_provider_is_deterministic() -> None:
    response = AIInterpretationResponse(candidates=(proposal("Excel", ("page:1:block:1",)),))
    provider = MockAIProvider(response)
    request = AIInterpretationRequest(evidence=(EvidenceContext(reference="page:1:block:1", original_text="Excel"),))

    assert provider.interpret_career_evidence(request) == response
    assert provider.interpret_career_evidence(request) == response

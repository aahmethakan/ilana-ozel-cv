from app.ai.career.schemas import AIInterpretationRequest, AIInterpretationResponse
from app.ai.career.validation import (
    CareerCandidateValidationResult,
    RejectedAIProposal,
    candidate_from_proposal,
)
from app.domain.document import CVDocument


def create_career_fact_candidates(
    document: CVDocument,
    response: AIInterpretationResponse,
    request: AIInterpretationRequest,
) -> CareerCandidateValidationResult:
    """Validate proposals against the CVDocument and evidence explicitly supplied to AI."""

    blocks = {block.stable_reference: block for block in document.blocks}
    allowed_references = {evidence.reference for evidence in request.evidence}
    candidates = []
    rejected = []
    for proposal in response.candidates:
        request_unknown_references = [
            reference
            for reference in proposal.evidence_references
            if reference not in allowed_references
        ]
        if request_unknown_references:
            rejected.append(
                RejectedAIProposal(
                    proposed_statement=proposal.proposed_statement,
                    reason="unknown_request_evidence_reference",
                )
            )
            continue
        unknown_references = [reference for reference in proposal.evidence_references if reference not in blocks]
        if unknown_references:
            rejected.append(
                RejectedAIProposal(
                    proposed_statement=proposal.proposed_statement,
                    reason="unknown_evidence_reference",
                )
            )
            continue
        source_text = "\n".join(blocks[reference].raw_text for reference in proposal.evidence_references)
        candidates.append(candidate_from_proposal(proposal, source_text))
    return CareerCandidateValidationResult(candidates=tuple(candidates), rejected_proposals=tuple(rejected))

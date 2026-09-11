from app.ai.career.schemas import AIInterpretationResponse
from app.ai.career.validation import (
    CareerCandidateValidationResult,
    RejectedAIProposal,
    candidate_from_proposal,
)
from app.domain.document import CVDocument


def create_career_fact_candidates(
    document: CVDocument, response: AIInterpretationResponse
) -> CareerCandidateValidationResult:
    """Validate AI proposal evidence against one CVDocument before retaining candidates."""

    blocks = {block.stable_reference: block for block in document.blocks}
    candidates = []
    rejected = []
    for proposal in response.candidates:
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

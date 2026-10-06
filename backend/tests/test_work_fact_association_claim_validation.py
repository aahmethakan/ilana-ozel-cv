import copy

from app.services.claim_validation import (
    ClaimKind, ClaimValidationStatus, GeneratedClaimProposal,
    WorkFactAssociationAssertion, claim_id, validate_generated_claim,
)
from app.services.generation_context.schemas import (
    EligibleWorkFactAssociation, GenerationContext, work_fact_association_evidence_id,
)
from app.services.claim_rendering import ClaimRenderingMode, render_validated_claim
from tests.test_claim_validation import context as base_context


def proposal(assertion: WorkFactAssociationAssertion) -> GeneratedClaimProposal:
    return GeneratedClaimProposal(
        claim_id=claim_id(claim_kind=ClaimKind.EXPERIENCE_BULLET, text="SAP used in role", assertions=(assertion,)),
        text="SAP used in role", claim_kind=ClaimKind.EXPERIENCE_BULLET, assertions=(assertion,),
    )


def associated_context() -> GenerationContext:
    base = base_context.__wrapped__()
    work = base.work_experiences[0]
    atomic = base.atomic_claims[0]
    association = EligibleWorkFactAssociation(
        association_id="association-1", association_evidence_id=work_fact_association_evidence_id(association_id="association-1"),
        atomic_evidence_id=atomic.evidence_id, work_record_id=work.record_id, work_candidate_id=work.candidate_id,
    )
    return base.model_copy(update={"work_fact_associations": (association,)})


def assertion(context: GenerationContext, **changes: str) -> WorkFactAssociationAssertion:
    association = context.work_fact_associations[0]
    values = {"association_evidence_id": association.association_evidence_id, "atomic_evidence_id": association.atomic_evidence_id,
              "work_record_id": association.work_record_id, "work_candidate_id": association.work_candidate_id}
    values.update(changes)
    return WorkFactAssociationAssertion(**values)


def test_exact_association_is_required_and_atomic_claims_remain_independent() -> None:
    context = associated_context()
    assert validate_generated_claim(context, proposal(assertion(context))).status is ClaimValidationStatus.VALID
    no_association = context.model_copy(update={"work_fact_associations": ()})
    assert validate_generated_claim(no_association, proposal(assertion(context))).status is ClaimValidationStatus.INVALID


def test_association_rejects_wrong_id_atomic_record_candidate_and_cross_pair() -> None:
    context = associated_context()
    for changes in ({"association_evidence_id": "work-fact-association:wrong"}, {"atomic_evidence_id": "atomic:wrong"},
                    {"work_record_id": "other-work"}, {"work_candidate_id": "other-candidate"}):
        assert validate_generated_claim(context, proposal(assertion(context, **changes))).status is ClaimValidationStatus.INVALID


def test_association_validation_does_not_mutate_context() -> None:
    context = associated_context()
    before = copy.deepcopy(context.model_dump(mode="json"))
    validate_generated_claim(context, proposal(assertion(context, work_record_id="other-work")))
    assert context.model_dump(mode="json") == before


def test_work_fact_exact_renders_only_canonical_atomic_text_and_lineage() -> None:
    context = associated_context()
    claim = proposal(assertion(context))
    rendered = render_validated_claim(context, claim, ClaimRenderingMode.WORK_FACT_EXACT)
    assert rendered.text == context.atomic_claims[0].statement
    assert rendered.structured_lineage.record_id == context.work_experiences[0].record_id
    assert rendered.structured_lineage.candidate_id == context.work_experiences[0].candidate_id
    assert context.atomic_claims[0].evidence_id in rendered.supporting_evidence_ids
    assert context.work_fact_associations[0].association_evidence_id in rendered.supporting_evidence_ids


def test_work_fact_exact_ignores_caller_claim_text() -> None:
    context = associated_context()
    item = assertion(context)
    injected = GeneratedClaimProposal(
        claim_id=claim_id(claim_kind=ClaimKind.EXPERIENCE_BULLET, text="Advanced SAP expert", assertions=(item,)),
        text="Advanced SAP expert", claim_kind=ClaimKind.EXPERIENCE_BULLET, assertions=(item,),
    )
    assert render_validated_claim(context, injected, ClaimRenderingMode.WORK_FACT_EXACT).text == "SAP"

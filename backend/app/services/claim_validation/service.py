from app.services.claim_validation.schemas import (
    AtomicClaimAssertion,
    ClaimValidationFinding,
    ClaimValidationFindingCode,
    ClaimValidationResult,
    ClaimValidationStatus,
    ContactFieldAssertion,
    EducationFieldAssertion,
    GeneratedClaimProposal,
    WorkFieldAssertion,
    WorkFactAssociationAssertion,
)
from app.services.generation_context.schemas import (
    EligibleAtomicClaim,
    EligibleContactField,
    EligibleWorkFactAssociation,
    EligibleStructuredField,
    GenerationContext,
)


def _finding(code: ClaimValidationFindingCode, index: int, evidence_id: str) -> ClaimValidationFinding:
    return ClaimValidationFinding(code=code, assertion_index=index, evidence_id=evidence_id)


def validate_generated_claim(generation_context: GenerationContext, claim: GeneratedClaimProposal) -> ClaimValidationResult:
    """Validate only explicit assertion-to-evidence equality, without interpreting prose."""

    findings: list[ClaimValidationFinding] = []
    for index, assertion in enumerate(claim.assertions):
        if isinstance(assertion, WorkFactAssociationAssertion):
            association = generation_context.find_eligible_evidence(assertion.association_evidence_id)
            atomic = generation_context.find_eligible_evidence(assertion.atomic_evidence_id)
            work_exists = any((item.record_id, item.candidate_id) == (assertion.work_record_id, assertion.work_candidate_id) for item in generation_context.work_experiences)
            if association is None or atomic is None:
                findings.append(_finding(ClaimValidationFindingCode.UNKNOWN_EVIDENCE, index, assertion.association_evidence_id if association is None else assertion.atomic_evidence_id))
            elif not isinstance(association, EligibleWorkFactAssociation):
                findings.append(_finding(ClaimValidationFindingCode.EVIDENCE_KIND_MISMATCH, index, assertion.association_evidence_id))
            elif not isinstance(atomic, EligibleAtomicClaim) or not work_exists:
                findings.append(_finding(ClaimValidationFindingCode.LINEAGE_MISMATCH, index, assertion.association_evidence_id))
            elif (association.atomic_evidence_id, association.work_record_id, association.work_candidate_id) != (assertion.atomic_evidence_id, assertion.work_record_id, assertion.work_candidate_id):
                findings.append(_finding(ClaimValidationFindingCode.LINEAGE_MISMATCH, index, assertion.association_evidence_id))
            continue
        evidence = generation_context.find_eligible_evidence(assertion.evidence_id)
        if evidence is None:
            findings.append(_finding(ClaimValidationFindingCode.UNKNOWN_EVIDENCE, index, assertion.evidence_id))
            continue
        if isinstance(assertion, AtomicClaimAssertion):
            if not isinstance(evidence, EligibleAtomicClaim):
                findings.append(_finding(ClaimValidationFindingCode.EVIDENCE_KIND_MISMATCH, index, assertion.evidence_id))
            elif evidence.claim_type != assertion.claim_type:
                findings.append(_finding(ClaimValidationFindingCode.FIELD_MISMATCH, index, assertion.evidence_id))
            elif evidence.statement != assertion.value:
                findings.append(_finding(ClaimValidationFindingCode.VALUE_MISMATCH, index, assertion.evidence_id))
            continue
        if isinstance(assertion, (WorkFieldAssertion, EducationFieldAssertion)):
            if not isinstance(evidence, EligibleStructuredField):
                findings.append(_finding(ClaimValidationFindingCode.EVIDENCE_KIND_MISMATCH, index, assertion.evidence_id))
            elif (evidence.record_type, evidence.record_id, evidence.candidate_id) != (assertion.record_type, assertion.record_id, assertion.candidate_id):
                findings.append(_finding(ClaimValidationFindingCode.LINEAGE_MISMATCH, index, assertion.evidence_id))
            elif evidence.field_name != assertion.field_name.value:
                findings.append(_finding(ClaimValidationFindingCode.FIELD_MISMATCH, index, assertion.evidence_id))
            elif evidence.value.value != assertion.value:
                findings.append(_finding(ClaimValidationFindingCode.VALUE_MISMATCH, index, assertion.evidence_id))
            continue
        if not isinstance(evidence, EligibleContactField):
            findings.append(_finding(ClaimValidationFindingCode.EVIDENCE_KIND_MISMATCH, index, assertion.evidence_id))
        elif evidence.field_name != assertion.field_name:
            findings.append(_finding(ClaimValidationFindingCode.FIELD_MISMATCH, index, assertion.evidence_id))
        elif evidence.value.value != assertion.value:
            findings.append(_finding(ClaimValidationFindingCode.VALUE_MISMATCH, index, assertion.evidence_id))
    return ClaimValidationResult(claim_id=claim.claim_id, status=ClaimValidationStatus.INVALID if findings else ClaimValidationStatus.VALID, findings=tuple(findings))

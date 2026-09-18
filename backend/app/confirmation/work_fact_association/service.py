from app.confirmation.work_fact_association.schemas import *
from app.domain.career import FactSource, SourceType, VerificationStatus
from app.domain.career.work_fact_association import WorkFactAssociation, work_fact_association_id


def _is_canonical_identifier(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def resolve_work_fact_association(candidate, action, *, corrected_work_record_id=None, corrected_work_candidate_id=None, allowed_targets: tuple[WorkFactAssociationTarget, ...] | None = None):
    if not isinstance(action, WorkFactAssociationAction):
        raise ValueError("Association resolution action must be a WorkFactAssociationAction.")

    record_id, candidate_id = candidate.work_record_id, candidate.work_candidate_id
    if action is WorkFactAssociationAction.REJECT:
        return WorkFactAssociationResolutionResult(candidate=candidate,status=WorkFactAssociationResolutionStatus.REJECTED,audit=WorkFactAssociationResolutionAudit(candidate_id=candidate.candidate_id,action=action,original_work_record_id=candidate.work_record_id,original_work_candidate_id=candidate.work_candidate_id))
    elif action is WorkFactAssociationAction.LEAVE_UNRESOLVED:
        return WorkFactAssociationResolutionResult(candidate=candidate,status=WorkFactAssociationResolutionStatus.UNRESOLVED,audit=WorkFactAssociationResolutionAudit(candidate_id=candidate.candidate_id,action=action,original_work_record_id=candidate.work_record_id,original_work_candidate_id=candidate.work_candidate_id))
    elif action is WorkFactAssociationAction.CORRECT_TARGET:
        if not (
            _is_canonical_identifier(corrected_work_record_id)
            and _is_canonical_identifier(corrected_work_candidate_id)
        ):
            raise ValueError("Correct target requires canonical record and candidate IDs.")
        if not isinstance(allowed_targets, tuple) or not all(
            isinstance(target, WorkFactAssociationTarget) for target in allowed_targets
        ):
            raise ValueError("Correct target requires a tuple of WorkFactAssociationTarget values.")
        if (corrected_work_record_id, corrected_work_candidate_id) not in {
            (target.work_record_id, target.work_candidate_id) for target in allowed_targets
        }:
            raise ValueError("Correct target must be an allowed exact work target.")
        record_id, candidate_id = corrected_work_record_id, corrected_work_candidate_id
    elif action is WorkFactAssociationAction.ACCEPT:
        pass
    else:
        raise ValueError("Unsupported association resolution action.")

    source=FactSource(source_type=SourceType.USER_INPUT)
    association=WorkFactAssociation(association_id=work_fact_association_id(atomic_evidence_id=candidate.atomic_evidence_id,work_record_id=record_id,work_candidate_id=candidate_id,verification_status=VerificationStatus.USER_PROVIDED,source=source),atomic_evidence_id=candidate.atomic_evidence_id,work_record_id=record_id,work_candidate_id=candidate_id,verification_status=VerificationStatus.USER_PROVIDED,source=source)
    return WorkFactAssociationResolutionResult(candidate=candidate,status=WorkFactAssociationResolutionStatus.RESOLVED,audit=WorkFactAssociationResolutionAudit(candidate_id=candidate.candidate_id,action=action,original_work_record_id=candidate.work_record_id,original_work_candidate_id=candidate.work_candidate_id,corrected_work_record_id=corrected_work_record_id,corrected_work_candidate_id=corrected_work_candidate_id,resulting_association_id=association.association_id),association=association)

import pytest
from pydantic import ValidationError

from app.domain.career import FactSource, SourceType, VerificationStatus
from app.domain.career.work_fact_association import work_fact_association_id
from app.services.generation_context.schemas import EligibleWorkFactAssociation, work_fact_association_evidence_id


def make(**changes: str) -> EligibleWorkFactAssociation:
    values = {"atomic_evidence_id": "atomic:1", "work_record_id": "R1", "work_candidate_id": "C1"}
    values.update(changes)
    source = FactSource(source_type=SourceType.USER_INPUT)
    values.setdefault("association_id", work_fact_association_id(atomic_evidence_id=values["atomic_evidence_id"], work_record_id=values["work_record_id"], work_candidate_id=values["work_candidate_id"], verification_status=VerificationStatus.USER_PROVIDED, source=source))
    return EligibleWorkFactAssociation(association_evidence_id=work_fact_association_evidence_id(association_id=values["association_id"]), **values)


def test_eligible_work_fact_association_is_deterministic_and_round_trips() -> None:
    value = make()
    assert EligibleWorkFactAssociation.model_validate(value.model_dump(mode="json")) == value
    assert make().association_evidence_id == value.association_evidence_id


@pytest.mark.parametrize("field,value", [("atomic_evidence_id", "atomic:2"), ("work_record_id", "R2"), ("work_candidate_id", "C2")])
def test_endpoint_changes_produce_new_phase_one_and_eligible_identity(field: str, value: str) -> None:
    assert make(**{field: value}).association_evidence_id != make().association_evidence_id


@pytest.mark.parametrize("field", ["association_id", "atomic_evidence_id", "work_record_id", "work_candidate_id"])
def test_rejects_noncanonical_or_extra_fields(field: str) -> None:
    with pytest.raises(ValidationError): make(**{field: " bad"})
    with pytest.raises(ValidationError): EligibleWorkFactAssociation.model_validate({**make().model_dump(mode="json"), "proposal_text": "no"})

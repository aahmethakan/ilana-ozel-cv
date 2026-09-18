from enum import Enum
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from app.confirmation.work_fact_association import (
    WorkFactAssociationAction,
    WorkFactAssociationTarget,
    resolve_work_fact_association,
)
from app.domain.career import FactSource, SourceType, VerificationStatus
from app.domain.career.work_fact_association import (
    WorkFactAssociation,
    WorkFactAssociationCandidate,
    work_fact_association_candidate_id,
    work_fact_association_id,
)


def candidate(source_type: SourceType, status: VerificationStatus) -> WorkFactAssociationCandidate:
    source = FactSource(source_type=source_type, reference="synthetic:association", original_text="Synthetic association")
    return WorkFactAssociationCandidate(candidate_id=work_fact_association_candidate_id(atomic_evidence_id="atomic:1", work_record_id="R1", work_candidate_id="C1", source=source), atomic_evidence_id="atomic:1", work_record_id="R1", work_candidate_id="C1", verification_status=status, source=source)


@pytest.mark.parametrize("source_type", [SourceType.SYSTEM_INFERENCE, SourceType.MASTER_CV, SourceType.USER_INPUT])
def test_association_candidates_are_always_unverified(source_type: SourceType) -> None:
    assert candidate(source_type, VerificationStatus.INFERRED_UNVERIFIED).verification_status is VerificationStatus.INFERRED_UNVERIFIED


@pytest.mark.parametrize("source_type,status", [(SourceType.SYSTEM_INFERENCE, VerificationStatus.VERIFIED), (SourceType.MASTER_CV, VerificationStatus.VERIFIED), (SourceType.USER_INPUT, VerificationStatus.USER_PROVIDED)])
def test_association_candidate_rejects_trusted_statuses(source_type: SourceType, status: VerificationStatus) -> None:
    with pytest.raises(ValidationError):
        candidate(source_type, status)


def test_trusted_association_rejects_master_cv_verified_direct_construction() -> None:
    with pytest.raises(ValidationError):
        trusted_association(SourceType.MASTER_CV, VerificationStatus.VERIFIED)


def trusted_association(
    source_type: SourceType,
    status: VerificationStatus,
    *,
    association_id: str | None = None,
) -> WorkFactAssociation:
    source = FactSource(
        source_type=source_type,
        reference="synthetic:association",
        original_text="Synthetic association",
    )
    return WorkFactAssociation(
        association_id=association_id
        or work_fact_association_id(
            atomic_evidence_id="atomic:1",
            work_record_id="R1",
            work_candidate_id="C1",
            verification_status=status,
            source=source,
        ),
        atomic_evidence_id="atomic:1",
        work_record_id="R1",
        work_candidate_id="C1",
        verification_status=status,
        source=source,
    )


@pytest.mark.parametrize(
    ("source_type", "status", "is_valid"),
    [
        (SourceType.SYSTEM_INFERENCE, VerificationStatus.INFERRED_UNVERIFIED, False),
        (SourceType.SYSTEM_INFERENCE, VerificationStatus.VERIFIED, False),
        (SourceType.SYSTEM_INFERENCE, VerificationStatus.USER_PROVIDED, False),
        (SourceType.MASTER_CV, VerificationStatus.INFERRED_UNVERIFIED, False),
        (SourceType.MASTER_CV, VerificationStatus.VERIFIED, False),
        (SourceType.MASTER_CV, VerificationStatus.USER_PROVIDED, False),
        (SourceType.USER_INPUT, VerificationStatus.INFERRED_UNVERIFIED, False),
        (SourceType.USER_INPUT, VerificationStatus.VERIFIED, False),
        (SourceType.USER_INPUT, VerificationStatus.USER_PROVIDED, True),
    ],
)
def test_trusted_association_source_status_matrix(
    source_type: SourceType, status: VerificationStatus, is_valid: bool
) -> None:
    if is_valid:
        association = trusted_association(source_type, status)
        assert association.source.source_type is SourceType.USER_INPUT
        assert association.verification_status is VerificationStatus.USER_PROVIDED
    else:
        with pytest.raises(ValidationError):
            trusted_association(source_type, status)


def test_trusted_association_rejects_invalid_state_with_recomputed_id() -> None:
    with pytest.raises(ValidationError):
        trusted_association(SourceType.MASTER_CV, VerificationStatus.VERIFIED)


def test_trusted_association_rejects_stale_id_for_valid_state() -> None:
    with pytest.raises(ValidationError):
        trusted_association(
            SourceType.USER_INPUT,
            VerificationStatus.USER_PROVIDED,
            association_id="work-fact-association:stale",
        )


def test_trusted_association_rejects_serialized_master_cv_verified_payload() -> None:
    source = FactSource(
        source_type=SourceType.MASTER_CV,
        reference="synthetic:association",
        original_text="Synthetic association",
    )
    payload = {
        "association_id": work_fact_association_id(
            atomic_evidence_id="atomic:1",
            work_record_id="R1",
            work_candidate_id="C1",
            verification_status=VerificationStatus.VERIFIED,
            source=source,
        ),
        "atomic_evidence_id": "atomic:1",
        "work_record_id": "R1",
        "work_candidate_id": "C1",
        "verification_status": VerificationStatus.VERIFIED.value,
        "source": source.model_dump(mode="json"),
    }
    with pytest.raises(ValidationError):
        WorkFactAssociation.model_validate(payload)


def test_accept_does_not_include_ai_proposal_prose_in_trusted_association_identity() -> None:
    first = resolve_work_fact_association(
        inferred_candidate("Proposal wording A"), WorkFactAssociationAction.ACCEPT
    )
    second = resolve_work_fact_association(
        inferred_candidate("Proposal wording B"), WorkFactAssociationAction.ACCEPT
    )

    assert first.association is not None
    assert second.association is not None
    assert first.association.association_id == second.association.association_id
    assert first.audit.candidate_id != second.audit.candidate_id


def inferred_candidate(
    proposal_text: str,
    *,
    atomic_evidence_id: str = "atomic:1",
    work_record_id: str = "R1",
    work_candidate_id: str = "C1",
) -> WorkFactAssociationCandidate:
    source = FactSource(
        source_type=SourceType.SYSTEM_INFERENCE,
        reference="synthetic:association",
        original_text=proposal_text,
    )
    return WorkFactAssociationCandidate(
        candidate_id=work_fact_association_candidate_id(
            atomic_evidence_id=atomic_evidence_id,
            work_record_id=work_record_id,
            work_candidate_id=work_candidate_id,
            source=source,
        ),
        atomic_evidence_id=atomic_evidence_id,
        work_record_id=work_record_id,
        work_candidate_id=work_candidate_id,
        verification_status=VerificationStatus.INFERRED_UNVERIFIED,
        source=source,
    )


def test_correct_target_converges_without_retaining_original_proposal_target() -> None:
    first = resolve_work_fact_association(
        inferred_candidate("Proposal A", work_record_id="R1", work_candidate_id="C1"),
        WorkFactAssociationAction.CORRECT_TARGET,
        corrected_work_record_id="R3",
        corrected_work_candidate_id="C3",
        allowed_targets=(WorkFactAssociationTarget(work_record_id="R3", work_candidate_id="C3"),),
    )
    second = resolve_work_fact_association(
        inferred_candidate("Proposal B", work_record_id="R2", work_candidate_id="C2"),
        WorkFactAssociationAction.CORRECT_TARGET,
        corrected_work_record_id="R3",
        corrected_work_candidate_id="C3",
        allowed_targets=(WorkFactAssociationTarget(work_record_id="R3", work_candidate_id="C3"),),
    )

    assert first.association is not None
    assert second.association is not None
    assert first.association.association_id == second.association.association_id
    assert (first.audit.original_work_record_id, first.audit.original_work_candidate_id) == ("R1", "C1")
    assert (second.audit.original_work_record_id, second.audit.original_work_candidate_id) == ("R2", "C2")


def test_accept_and_correct_target_converge_on_same_trusted_relationship() -> None:
    accepted = resolve_work_fact_association(
        inferred_candidate("Proposal already targeting final", work_record_id="R3", work_candidate_id="C3"),
        WorkFactAssociationAction.ACCEPT,
    )
    corrected = resolve_work_fact_association(
        inferred_candidate("Proposal targeting elsewhere", work_record_id="R1", work_candidate_id="C1"),
        WorkFactAssociationAction.CORRECT_TARGET,
        corrected_work_record_id="R3",
        corrected_work_candidate_id="C3",
        allowed_targets=(WorkFactAssociationTarget(work_record_id="R3", work_candidate_id="C3"),),
    )

    assert accepted.association is not None
    assert corrected.association is not None
    assert accepted.association.association_id == corrected.association.association_id
    assert accepted.audit.action is WorkFactAssociationAction.ACCEPT
    assert corrected.audit.action is WorkFactAssociationAction.CORRECT_TARGET


@pytest.mark.parametrize(
    "candidate_kwargs",
    [
        {"atomic_evidence_id": "atomic:2"},
        {"work_record_id": "R2"},
        {"work_candidate_id": "C2"},
    ],
)
def test_trusted_association_identity_remains_sensitive_to_authoritative_endpoints(
    candidate_kwargs: dict[str, str],
) -> None:
    baseline = resolve_work_fact_association(
        inferred_candidate("Proposal baseline"), WorkFactAssociationAction.ACCEPT
    )
    changed = resolve_work_fact_association(
        inferred_candidate("Different proposal text", **candidate_kwargs),
        WorkFactAssociationAction.ACCEPT,
    )

    assert baseline.association is not None
    assert changed.association is not None
    assert baseline.association.association_id != changed.association.association_id


def test_trusted_association_serialization_excludes_candidate_lineage_and_proposal_prose() -> None:
    candidate_value = inferred_candidate("AI proposal text must remain only in candidate lineage")
    result = resolve_work_fact_association(candidate_value, WorkFactAssociationAction.ACCEPT)

    assert result.association is not None
    serialized = result.association.model_dump(mode="json")
    rendered = str(serialized)
    assert candidate_value.candidate_id not in rendered
    assert candidate_value.source.original_text not in rendered
    assert serialized["source"] == {"source_type": SourceType.USER_INPUT.value, "reference": None, "original_text": None}
    assert result.audit.candidate_id == candidate_value.candidate_id


@pytest.mark.parametrize(
    ("corrected_work_record_id", "corrected_work_candidate_id"),
    [
        (None, "C3"),
        ("R3", None),
        ("", "C3"),
        ("R3", ""),
        ("   ", "C3"),
        ("R3", "   "),
        ("\t", "C3"),
        ("R3", "\n"),
        (" R3", "C3"),
        ("R3 ", "C3"),
        ("R3", " C3"),
        ("R3", "C3 "),
        ("   ", "\t"),
    ],
)
def test_correct_target_rejects_blank_exact_target_identifiers(
    corrected_work_record_id: str | None, corrected_work_candidate_id: str | None
) -> None:
    with pytest.raises(ValueError):
        resolve_work_fact_association(
            inferred_candidate("Synthetic proposal"),
            WorkFactAssociationAction.CORRECT_TARGET,
            corrected_work_record_id=corrected_work_record_id,
            corrected_work_candidate_id=corrected_work_candidate_id,
        )


def test_correct_target_preserves_canonical_identifiers_exactly() -> None:
    result = resolve_work_fact_association(
        inferred_candidate("Synthetic proposal"),
        WorkFactAssociationAction.CORRECT_TARGET,
        corrected_work_record_id="R3",
        corrected_work_candidate_id="C3",
        allowed_targets=(WorkFactAssociationTarget(work_record_id="R3", work_candidate_id="C3"),),
    )

    assert result.association is not None
    assert (result.association.work_record_id, result.association.work_candidate_id) == ("R3", "C3")
    assert (result.audit.corrected_work_record_id, result.audit.corrected_work_candidate_id) == ("R3", "C3")


def test_trusted_association_direct_construction_rejects_noncanonical_endpoint_id() -> None:
    source = FactSource(source_type=SourceType.USER_INPUT)
    with pytest.raises(ValidationError):
        WorkFactAssociation(
            association_id=work_fact_association_id(
                atomic_evidence_id="atomic:1",
                work_record_id=" R3",
                work_candidate_id="C3",
                verification_status=VerificationStatus.USER_PROVIDED,
                source=source,
            ),
            atomic_evidence_id="atomic:1",
            work_record_id=" R3",
            work_candidate_id="C3",
            verification_status=VerificationStatus.USER_PROVIDED,
            source=source,
        )


def direct_candidate(**overrides: str) -> WorkFactAssociationCandidate:
    endpoints = {
        "atomic_evidence_id": "atomic:x",
        "work_record_id": "R1",
        "work_candidate_id": "C1",
    }
    endpoints.update(overrides)
    source = FactSource(source_type=SourceType.SYSTEM_INFERENCE, reference="synthetic:source")
    return WorkFactAssociationCandidate(
        candidate_id=work_fact_association_candidate_id(**endpoints, source=source),
        verification_status=VerificationStatus.INFERRED_UNVERIFIED,
        source=source,
        **endpoints,
    )


def direct_trusted_association(**overrides: str) -> WorkFactAssociation:
    endpoints = {
        "atomic_evidence_id": "atomic:x",
        "work_record_id": "R1",
        "work_candidate_id": "C1",
    }
    endpoints.update(overrides)
    source = FactSource(source_type=SourceType.USER_INPUT)
    return WorkFactAssociation(
        association_id=work_fact_association_id(
            **endpoints,
            verification_status=VerificationStatus.USER_PROVIDED,
            source=source,
        ),
        verification_status=VerificationStatus.USER_PROVIDED,
        source=source,
        **endpoints,
    )


@pytest.mark.parametrize(
    ("field_name", "malformed_value"),
    [
        ("atomic_evidence_id", ""),
        ("atomic_evidence_id", "   "),
        ("atomic_evidence_id", " atomic:x"),
        ("atomic_evidence_id", "atomic:x "),
        ("work_record_id", ""),
        ("work_record_id", "   "),
        ("work_record_id", " R1"),
        ("work_record_id", "R1 "),
        ("work_candidate_id", ""),
        ("work_candidate_id", "   "),
        ("work_candidate_id", " C1"),
        ("work_candidate_id", "C1 "),
    ],
)
def test_candidate_rejects_noncanonical_endpoint_identifiers_with_recomputed_id(
    field_name: str, malformed_value: str
) -> None:
    with pytest.raises(ValidationError):
        direct_candidate(**{field_name: malformed_value})


@pytest.mark.parametrize(
    ("field_name", "malformed_value"),
    [
        ("atomic_evidence_id", ""),
        ("atomic_evidence_id", "   "),
        ("atomic_evidence_id", " atomic:x"),
        ("atomic_evidence_id", "atomic:x "),
        ("work_record_id", ""),
        ("work_record_id", "   "),
        ("work_record_id", " R1"),
        ("work_record_id", "R1 "),
        ("work_candidate_id", ""),
        ("work_candidate_id", "   "),
        ("work_candidate_id", " C1"),
        ("work_candidate_id", "C1 "),
    ],
)
def test_trusted_association_rejects_noncanonical_endpoint_identifiers_with_recomputed_id(
    field_name: str, malformed_value: str
) -> None:
    with pytest.raises(ValidationError):
        direct_trusted_association(**{field_name: malformed_value})


def test_direct_association_models_preserve_canonical_endpoint_values_and_identity() -> None:
    candidate_value = direct_candidate()
    association = direct_trusted_association()

    assert candidate_value.model_validate(candidate_value.model_dump(mode="json")) == candidate_value
    assert association.model_validate(association.model_dump(mode="json")) == association


def test_direct_association_models_reject_whitespace_modified_identity_values() -> None:
    candidate_value = direct_candidate()
    association = direct_trusted_association()

    with pytest.raises(ValidationError):
        WorkFactAssociationCandidate.model_validate(
            {**candidate_value.model_dump(mode="json"), "candidate_id": f" {candidate_value.candidate_id}"}
        )
    with pytest.raises(ValidationError):
        WorkFactAssociation.model_validate(
            {**association.model_dump(mode="json"), "association_id": f"{association.association_id} "}
        )


class UnrelatedAction(Enum):
    ACCEPT = "accept"


@pytest.mark.parametrize(
    "invalid_action",
    ["accept", "ACCEPT", "reject", "", "   ", 1, 0, True, False, None, object(), UnrelatedAction.ACCEPT],
)
def test_resolution_rejects_non_enum_action_without_manufacturing_association(
    invalid_action: object,
) -> None:
    with pytest.raises(ValueError):
        resolve_work_fact_association(inferred_candidate("Synthetic proposal"), invalid_action)


@pytest.mark.parametrize(
    "action",
    [WorkFactAssociationAction.REJECT, WorkFactAssociationAction.LEAVE_UNRESOLVED],
)
def test_non_promoting_enum_actions_create_no_association(action: WorkFactAssociationAction) -> None:
    result = resolve_work_fact_association(inferred_candidate("Synthetic proposal"), action)

    assert result.association is None


def test_accept_and_correct_target_enum_actions_create_trusted_associations() -> None:
    accepted = resolve_work_fact_association(
        inferred_candidate("Synthetic proposal"), WorkFactAssociationAction.ACCEPT
    )
    corrected = resolve_work_fact_association(
        inferred_candidate("Synthetic proposal"),
        WorkFactAssociationAction.CORRECT_TARGET,
        corrected_work_record_id="R3",
        corrected_work_candidate_id="C3",
        allowed_targets=(WorkFactAssociationTarget(work_record_id="R3", work_candidate_id="C3"),),
    )

    for result in (accepted, corrected):
        assert result.association is not None
        assert result.association.source.source_type is SourceType.USER_INPUT
        assert result.association.verification_status is VerificationStatus.USER_PROVIDED


def test_resolution_rejects_non_candidate_input_before_manufacturing_association() -> None:
    forged = SimpleNamespace(
        candidate_id="forged-candidate",
        atomic_evidence_id="atomic:1",
        work_record_id="R1",
        work_candidate_id="C1",
    )

    with pytest.raises(ValueError):
        resolve_work_fact_association(forged, WorkFactAssociationAction.ACCEPT)


@pytest.mark.parametrize(
    ("corrected_work_record_id", "corrected_work_candidate_id"),
    [
        ("Example Manufacturing", "C3"),
        ("R3", "Senior Production Engineer"),
        ("Manufacturing Lead", "Role selected from free text"),
    ],
)
def test_correct_target_rejects_company_title_and_free_text_as_target_identifiers(
    corrected_work_record_id: str, corrected_work_candidate_id: str
) -> None:
    with pytest.raises(ValueError):
        resolve_work_fact_association(
            inferred_candidate("Synthetic proposal"),
            WorkFactAssociationAction.CORRECT_TARGET,
            corrected_work_record_id=corrected_work_record_id,
            corrected_work_candidate_id=corrected_work_candidate_id,
        )


@pytest.mark.parametrize(
    ("record_id", "candidate_id", "allowed"),
    [("R1", "C1", True), ("R2", "C2", True), ("R3", "C3", True), ("R1", "C2", False), ("R2", "C1", False), ("UNKNOWN", "C1", False), ("R1", "UNKNOWN", False)],
)
def test_correct_target_requires_exact_allowed_target_pair(record_id: str, candidate_id: str, allowed: bool) -> None:
    kwargs = dict(
        corrected_work_record_id=record_id,
        corrected_work_candidate_id=candidate_id,
        allowed_targets=(
            WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1"),
            WorkFactAssociationTarget(work_record_id="R2", work_candidate_id="C2"),
            WorkFactAssociationTarget(work_record_id="R3", work_candidate_id="C3"),
        ),
    )
    if allowed:
        result = resolve_work_fact_association(inferred_candidate("Synthetic"), WorkFactAssociationAction.CORRECT_TARGET, **kwargs)
        assert result.association is not None
    else:
        with pytest.raises(ValueError):
            resolve_work_fact_association(inferred_candidate("Synthetic"), WorkFactAssociationAction.CORRECT_TARGET, **kwargs)


def test_correct_target_rejects_non_target_value_objects_in_allowed_context() -> None:
    forged_target = SimpleNamespace(work_record_id="R3", work_candidate_id="C3")

    with pytest.raises(ValueError):
        resolve_work_fact_association(
            inferred_candidate("Synthetic"),
            WorkFactAssociationAction.CORRECT_TARGET,
            corrected_work_record_id="R3",
            corrected_work_candidate_id="C3",
            allowed_targets=(forged_target,),
        )


class TargetIterable:
    def __iter__(self):
        yield WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1")


@dataclass(frozen=True)
class TargetDataclass:
    work_record_id: str
    work_candidate_id: str


class TargetPydanticModel(BaseModel):
    work_record_id: str
    work_candidate_id: str


class TargetLike:
    work_record_id = "R1"
    work_candidate_id = "C1"


@pytest.mark.parametrize(
    "allowed_targets",
    [
        [WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1")],
        {WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1")},
        frozenset({WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1")}),
        (target for target in (WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1"),)),
        iter((WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1"),)),
        {"work_record_id": "R1", "work_candidate_id": "C1"},
        "R1/C1",
        TargetIterable(),
        None,
        (),
    ],
)
def test_correct_target_rejects_non_tuple_or_empty_allowed_targets(allowed_targets: object) -> None:
    with pytest.raises(ValueError):
        resolve_work_fact_association(
            inferred_candidate("Synthetic"), WorkFactAssociationAction.CORRECT_TARGET,
            corrected_work_record_id="R1", corrected_work_candidate_id="C1", allowed_targets=allowed_targets,
        )


@pytest.mark.parametrize(
    "entry",
    [
        SimpleNamespace(work_record_id="R1", work_candidate_id="C1"),
        {"work_record_id": "R1", "work_candidate_id": "C1"},
        ("R1", "C1"),
        None,
        "R1",
        UnrelatedAction.ACCEPT,
        TargetLike(),
        TargetDataclass("R1", "C1"),
        TargetPydanticModel(work_record_id="R1", work_candidate_id="C1"),
    ],
)
def test_correct_target_rejects_forged_target_entries(entry: object) -> None:
    with pytest.raises(ValueError):
        resolve_work_fact_association(inferred_candidate("Synthetic"), WorkFactAssociationAction.CORRECT_TARGET, corrected_work_record_id="R1", corrected_work_candidate_id="C1", allowed_targets=(entry,))


@pytest.mark.parametrize(
    ("targets", "succeeds"),
    [
        ((WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1"), TargetLike()), False),
        ((TargetLike(), WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1")), False),
        ((WorkFactAssociationTarget(work_record_id="R2", work_candidate_id="C2"), TargetLike()), False),
        ((TargetLike(), WorkFactAssociationTarget(work_record_id="R2", work_candidate_id="C2")), False),
        ((WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1"), TargetLike()), False),
        ((TargetLike(), WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1")), False),
        ((WorkFactAssociationTarget(work_record_id="R2", work_candidate_id="C2"), WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1")), True),
        ((WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1"), WorkFactAssociationTarget(work_record_id="R2", work_candidate_id="C2")), True),
    ],
)
def test_correct_target_validates_all_context_entries_before_membership(targets: tuple[object, ...], succeeds: bool) -> None:
    if succeeds:
        assert resolve_work_fact_association(inferred_candidate("Synthetic"), WorkFactAssociationAction.CORRECT_TARGET, corrected_work_record_id="R1", corrected_work_candidate_id="C1", allowed_targets=targets).association is not None
    else:
        with pytest.raises(ValueError):
            resolve_work_fact_association(inferred_candidate("Synthetic"), WorkFactAssociationAction.CORRECT_TARGET, corrected_work_record_id="R1", corrected_work_candidate_id="C1", allowed_targets=targets)


def test_target_context_does_not_affect_identity_or_leak() -> None:
    t1 = WorkFactAssociationTarget(work_record_id="R1", work_candidate_id="C1")
    t2 = WorkFactAssociationTarget(work_record_id="R2", work_candidate_id="C2")
    t3 = WorkFactAssociationTarget(work_record_id="R3", work_candidate_id="C3")
    candidate_value = inferred_candidate("Synthetic", work_record_id="R2", work_candidate_id="C2")
    contexts = ((t1,), (t1, t1), (t1, t2), (t2, t1), (t1, t2, t3), (t3, t2, t1))
    results = [resolve_work_fact_association(candidate_value, WorkFactAssociationAction.CORRECT_TARGET, corrected_work_record_id="R1", corrected_work_candidate_id="C1", allowed_targets=context) for context in contexts]
    assert {result.association.association_id for result in results if result.association}.__len__() == 1
    association = results[-1].association
    assert association is not None
    assert association.model_dump(mode="json") == {"association_id": association.association_id, "atomic_evidence_id": "atomic:1", "work_record_id": "R1", "work_candidate_id": "C1", "verification_status": "user_provided", "source": {"source_type": "user_input", "reference": None, "original_text": None}}
    audit = results[-1].audit.model_dump(mode="json")
    assert "allowed_targets" not in audit and "R3" not in str(audit)

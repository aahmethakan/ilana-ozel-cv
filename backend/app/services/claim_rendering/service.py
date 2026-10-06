from app.domain.career import CareerDate
from app.services.claim_rendering.schemas import (
    ClaimNotRenderableError,
    ClaimRenderingErrorCode,
    ClaimRenderingMode,
    RenderedClaim,
    StructuredClaimLineage,
    rendered_claim_id,
)
from app.services.claim_validation import (
    AtomicClaimAssertion,
    ContactFieldAssertion,
    EducationFieldAssertion,
    GeneratedClaimProposal,
    WorkFieldAssertion,
    WorkFactAssociationAssertion,
    validate_generated_claim,
)
from app.services.evidence_convergence import EducationField, WorkExperienceField
from app.services.generation_context import EligibleAtomicClaim, GenerationContext


def _date_text(value: CareerDate) -> str:
    """Render a career date without inventing a day or locale-specific wording."""

    return str(value.year) if value.month is None else f"{value.year}-{value.month:02d}"


def _error(code: ClaimRenderingErrorCode, message: str) -> None:
    raise ClaimNotRenderableError(code, message)


def _require_exactly(assertions: tuple[object, ...], assertion_type: type, mode: ClaimRenderingMode):
    if len(assertions) != 1:
        _error(ClaimRenderingErrorCode.UNEXPECTED_ASSERTION, f"{mode.value} requires exactly one assertion.")
    assertion = assertions[0]
    if not isinstance(assertion, assertion_type):
        _error(ClaimRenderingErrorCode.ASSERTION_SET_MISMATCH, f"{mode.value} received an incompatible assertion kind.")
    return assertion


def _structured_fields(
    assertions: tuple[object, ...],
    assertion_type: type,
    allowed: set[object],
    required: set[object],
    mode: ClaimRenderingMode,
) -> dict[object, object]:
    if not assertions:
        _error(ClaimRenderingErrorCode.MISSING_REQUIRED_ASSERTION, f"{mode.value} requires assertions.")
    if not all(isinstance(item, assertion_type) for item in assertions):
        _error(ClaimRenderingErrorCode.ASSERTION_SET_MISMATCH, f"{mode.value} received an incompatible assertion kind.")
    fields = {item.field_name: item for item in assertions}
    if len(fields) != len(assertions):
        _error(ClaimRenderingErrorCode.UNEXPECTED_ASSERTION, f"{mode.value} cannot consume duplicate fields.")
    if unexpected := set(fields) - allowed:
        _error(ClaimRenderingErrorCode.UNEXPECTED_ASSERTION, f"{mode.value} cannot consume fields: {sorted(str(item) for item in unexpected)}.")
    if missing := required - set(fields):
        _error(ClaimRenderingErrorCode.MISSING_REQUIRED_ASSERTION, f"{mode.value} is missing fields: {sorted(str(item) for item in missing)}.")
    lineages = {(item.record_id, item.candidate_id) for item in assertions}
    if len(lineages) != 1:
        _error(ClaimRenderingErrorCode.LINEAGE_MISMATCH, f"{mode.value} assertions must share one record and candidate lineage.")
    return fields


def _work_identity(assertions: tuple[object, ...]) -> str:
    fields = _structured_fields(
        assertions,
        WorkFieldAssertion,
        {WorkExperienceField.COMPANY, WorkExperienceField.TITLE},
        {WorkExperienceField.COMPANY, WorkExperienceField.TITLE},
        ClaimRenderingMode.WORK_IDENTITY,
    )
    return f"{fields[WorkExperienceField.TITLE].value} — {fields[WorkExperienceField.COMPANY].value}"


def _work_date(assertions: tuple[object, ...]) -> str:
    fields = _structured_fields(
        assertions,
        WorkFieldAssertion,
        {WorkExperienceField.START_DATE, WorkExperienceField.END_DATE, WorkExperienceField.IS_CURRENT},
        {WorkExperienceField.START_DATE},
        ClaimRenderingMode.WORK_DATE,
    )
    start = fields[WorkExperienceField.START_DATE].value
    end = fields.get(WorkExperienceField.END_DATE)
    current = fields.get(WorkExperienceField.IS_CURRENT)
    if end is not None and current is not None:
        _error(ClaimRenderingErrorCode.UNSUPPORTED_FIELD_COMBINATION, "Work date rendering cannot consume both end date and currentness.")
    if current is not None and current.value is True:
        return f"{_date_text(start)} – Present"
    if end is not None:
        return f"{_date_text(start)} – {_date_text(end.value)}"
    return _date_text(start)


def _education_identity(assertions: tuple[object, ...]) -> str:
    fields = _structured_fields(
        assertions,
        EducationFieldAssertion,
        {EducationField.INSTITUTION, EducationField.DEGREE, EducationField.FIELD_OF_STUDY},
        {EducationField.INSTITUTION},
        ClaimRenderingMode.EDUCATION_IDENTITY,
    )
    institution = fields[EducationField.INSTITUTION].value
    degree = fields.get(EducationField.DEGREE)
    field_of_study = fields.get(EducationField.FIELD_OF_STUDY)
    prefix = ", ".join(item.value for item in (degree, field_of_study) if item is not None)
    return f"{prefix} — {institution}" if prefix else institution


def _education_date(assertions: tuple[object, ...]) -> str:
    fields = _structured_fields(
        assertions,
        EducationFieldAssertion,
        {EducationField.START_DATE, EducationField.END_DATE},
        set(),
        ClaimRenderingMode.EDUCATION_DATE,
    )
    start = fields.get(EducationField.START_DATE)
    end = fields.get(EducationField.END_DATE)
    if start is None and end is None:
        _error(ClaimRenderingErrorCode.MISSING_REQUIRED_ASSERTION, "Education date rendering requires a date assertion.")
    if start is None:
        return _date_text(end.value)
    if end is None:
        return _date_text(start.value)
    return f"{_date_text(start.value)} – {_date_text(end.value)}"


def _render_text(mode: ClaimRenderingMode, assertions: tuple[object, ...]) -> str:
    if mode is ClaimRenderingMode.WORK_FACT_EXACT:
        return ""  # resolved from eligible atomic evidence below; caller text is never consumed.
    if mode is ClaimRenderingMode.ATOMIC_EXACT:
        return _require_exactly(assertions, AtomicClaimAssertion, mode).value
    if mode is ClaimRenderingMode.CONTACT_EXACT:
        return _require_exactly(assertions, ContactFieldAssertion, mode).value
    if mode is ClaimRenderingMode.WORK_IDENTITY:
        return _work_identity(assertions)
    if mode is ClaimRenderingMode.WORK_DATE:
        return _work_date(assertions)
    if mode is ClaimRenderingMode.EDUCATION_IDENTITY:
        return _education_identity(assertions)
    if mode is ClaimRenderingMode.EDUCATION_DATE:
        return _education_date(assertions)
    _error(ClaimRenderingErrorCode.ASSERTION_SET_MISMATCH, "No deterministic renderer exists for this mode.")


def render_validated_claim(
    generation_context: GenerationContext,
    claim: GeneratedClaimProposal,
    rendering_mode: ClaimRenderingMode,
) -> RenderedClaim:
    """Rerun validation and deterministically render every assertion exactly once."""

    validation = validate_generated_claim(generation_context, claim)
    if validation.findings:
        _error(ClaimRenderingErrorCode.CLAIM_VALIDATION_FAILED, "Claim assertions are not fully supported by this generation context.")
    assertions = tuple(claim.assertions)
    if rendering_mode is ClaimRenderingMode.WORK_FACT_EXACT:
        assertion = _require_exactly(assertions, WorkFactAssociationAssertion, rendering_mode)
        atomic = generation_context.find_eligible_evidence(assertion.atomic_evidence_id)
        if atomic is None or not isinstance(atomic, EligibleAtomicClaim):
            _error(ClaimRenderingErrorCode.CLAIM_VALIDATION_FAILED, "Associated atomic evidence is not eligible.")
        text = atomic.statement
        evidence_ids = tuple(sorted((assertion.association_evidence_id, assertion.atomic_evidence_id)))
        lineage = StructuredClaimLineage(record_type="work", record_id=assertion.work_record_id, candidate_id=assertion.work_candidate_id)
    else:
        text = _render_text(rendering_mode, assertions)
        evidence_ids = tuple(sorted(item.evidence_id for item in assertions))
        lineage = None
    structured = tuple(item for item in assertions if isinstance(item, (WorkFieldAssertion, EducationFieldAssertion)))
    if structured:
        lineages = {(item.record_type, item.record_id, item.candidate_id) for item in structured}
        if len(lineages) != 1:
            _error(ClaimRenderingErrorCode.LINEAGE_MISMATCH, "Structured rendered assertions must share one lineage.")
        record_type, record_id, candidate_id = lineages.pop()
        lineage = StructuredClaimLineage(record_type=record_type, record_id=record_id, candidate_id=candidate_id)
    return RenderedClaim(
        rendered_claim_id=rendered_claim_id(
            rendering_mode=rendering_mode,
            text=text,
            source_claim_id=claim.claim_id,
            supporting_evidence_ids=evidence_ids,
            structured_lineage=lineage,
        ),
        text=text,
        claim_kind=claim.claim_kind,
        source_claim_id=claim.claim_id,
        supporting_evidence_ids=evidence_ids,
        rendering_mode=rendering_mode,
        structured_lineage=lineage,
    )

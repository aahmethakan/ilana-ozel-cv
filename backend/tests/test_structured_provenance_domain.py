import inspect

import pytest
from pydantic import ValidationError

from app.domain.career import (
    CareerDate,
    CareerFact,
    FactSource,
    Metric,
    ProvenancedBool,
    ProvenancedCareerDate,
    ProvenancedText,
    ProvenancedValue,
    SourceType,
    VerificationStatus,
)
from app.domain.career import facts as facts_module


def source(source_type: SourceType, reference: str = "page:1:block:1") -> FactSource:
    return FactSource(source_type=source_type, reference=reference, original_text="Synthetic source evidence")


def text_value(
    value: str = "Engineer",
    status: VerificationStatus = VerificationStatus.VERIFIED,
    value_source: FactSource | None = None,
    evidence_sources: tuple[FactSource, ...] = (),
) -> ProvenancedText:
    return ProvenancedText(
        value=value,
        verification_status=status,
        value_source=value_source or source(SourceType.MASTER_CV),
        evidence_sources=evidence_sources,
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (VerificationStatus.VERIFIED, True),
        (VerificationStatus.USER_PROVIDED, True),
        (VerificationStatus.INFERRED_UNVERIFIED, False),
    ],
)
def test_claim_usability_is_central_and_status_based(status: VerificationStatus, expected: bool) -> None:
    value_source = source(SourceType.USER_INPUT) if status is VerificationStatus.USER_PROVIDED else source(SourceType.MASTER_CV)
    value = text_value(status=status, value_source=value_source)

    assert value.is_claim_usable is expected
    fact = CareerFact(statement="Synthetic fact", verification_status=status, source=value_source)
    assert fact.is_claim_usable is expected


def test_source_and_verification_are_explicit_and_preserve_supporting_evidence() -> None:
    original = source(SourceType.MASTER_CV, "page:1:block:7")
    corrected = text_value(
        value="Engineer",
        status=VerificationStatus.USER_PROVIDED,
        value_source=source(SourceType.USER_INPUT, "structured_question:role:title"),
        evidence_sources=(original, source(SourceType.MASTER_CV, "page:1:block:8")),
    )
    ambiguous_master_cv = text_value("Senior Engineer", VerificationStatus.INFERRED_UNVERIFIED)
    inferred = text_value(
        "Managed 20 people",
        VerificationStatus.INFERRED_UNVERIFIED,
        source(SourceType.SYSTEM_INFERENCE),
    )

    assert corrected.is_claim_usable is True
    assert corrected.evidence_sources == (original, source(SourceType.MASTER_CV, "page:1:block:8"))
    assert ambiguous_master_cv.is_claim_usable is False
    assert inferred.is_claim_usable is False


def test_source_consistency_rejects_impossible_current_value_origins() -> None:
    with pytest.raises(ValidationError):
        text_value(status=VerificationStatus.VERIFIED, value_source=source(SourceType.USER_INPUT))
    with pytest.raises(ValidationError):
        text_value(status=VerificationStatus.VERIFIED, value_source=source(SourceType.SYSTEM_INFERENCE))

    explicit = text_value(status=VerificationStatus.USER_PROVIDED, value_source=source(SourceType.USER_INPUT))
    assert explicit.evidence_sources == ()


def test_provenanced_values_are_independent_immutable_and_unicode_safe() -> None:
    company = text_value("Örnek Şirket", VerificationStatus.USER_PROVIDED, source(SourceType.USER_INPUT))
    title = text_value("Kıdemli Mühendis", VerificationStatus.INFERRED_UNVERIFIED)

    assert company.is_claim_usable is True and title.is_claim_usable is False
    assert company.value == "Örnek Şirket"
    with pytest.raises(ValidationError):
        company.value = "Başka Şirket"
    with pytest.raises(ValidationError):
        company.value_source.reference = "changed"


def test_provenanced_text_rejects_blank_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        text_value("   ")
    with pytest.raises(ValidationError):
        ProvenancedText(
            value="Engineer",
            verification_status=VerificationStatus.VERIFIED,
            value_source=source(SourceType.MASTER_CV),
            unexpected=True,
        )


def test_generic_string_values_remain_type_agnostic() -> None:
    value = ProvenancedValue[str](
        value="",
        verification_status=VerificationStatus.VERIFIED,
        value_source=source(SourceType.MASTER_CV),
    )

    assert value.value == ""


def test_generic_round_trips_preserve_types_and_provenance() -> None:
    values = (
        text_value(),
        ProvenancedCareerDate(
            value=CareerDate(year=2024, month=5),
            verification_status=VerificationStatus.VERIFIED,
            value_source=source(SourceType.MASTER_CV),
        ),
        ProvenancedBool(
            value=True,
            verification_status=VerificationStatus.USER_PROVIDED,
            value_source=source(SourceType.USER_INPUT),
        ),
    )

    for value in values:
        restored = type(value).model_validate(value.model_dump(mode="json"))
        assert restored == value

    assert isinstance(values[1].value, CareerDate)
    assert isinstance(values[2].value, bool)


def test_career_date_preserves_partial_precision_and_safe_comparison() -> None:
    year_only = CareerDate(year=2024)
    may = CareerDate(year=2024, month=5)
    june = CareerDate(year=2024, month=6)
    prior_year = CareerDate(year=2023)

    assert year_only.model_dump(mode="json") == {"year": 2024, "month": None}
    assert may.model_dump(mode="json") == {"year": 2024, "month": 5}
    assert year_only.definitely_before(may) is False
    assert year_only.definitely_after(may) is False
    assert may.definitely_before(june) is True
    assert may.definitely_after(prior_year) is True
    assert prior_year.definitely_before(may) is True
    assert CareerDate(year=2025).definitely_after(CareerDate(year=2024, month=12)) is True
    assert CareerDate(year=2024).definitely_before(CareerDate(year=2024)) is False
    assert may.definitely_before(CareerDate(year=2024, month=5)) is False
    assert type(year_only).model_validate(year_only.model_dump(mode="json")) == year_only


@pytest.mark.parametrize("month", (0, 13))
def test_career_date_rejects_invalid_months(month: int) -> None:
    with pytest.raises(ValidationError):
        CareerDate(year=2024, month=month)


def test_career_date_rejects_day_and_present_and_is_immutable() -> None:
    with pytest.raises(ValidationError):
        CareerDate(year=2024, day=1)
    with pytest.raises(ValidationError):
        CareerDate(year="Present")

    date = CareerDate(year=2024)
    with pytest.raises(ValidationError):
        date.month = 5


def test_domain_foundation_does_not_change_existing_structured_flows() -> None:
    source_text = inspect.getsource(facts_module)

    assert "is_verification_usable" in source_text
    assert "WorkExperience" not in inspect.getsource(CareerFact)


def test_career_fact_serialization_and_cross_field_trust_remain_independent() -> None:
    fact = CareerFact(
        statement="Synthetic delivery",
        verification_status=VerificationStatus.VERIFIED,
        source=source(SourceType.MASTER_CV),
        skills=("Planning",),
        tools=("SAP",),
        certifications=("PMP",),
        language="English",
        language_proficiency="B2",
        metrics=(Metric(value=12, unit="%", label="synthetic improvement"),),
    )
    company = text_value("ACME")
    title = text_value("Senior Engineer", VerificationStatus.INFERRED_UNVERIFIED)
    date = ProvenancedCareerDate(
        value=CareerDate(year=2024),
        verification_status=VerificationStatus.INFERRED_UNVERIFIED,
        value_source=source(SourceType.MASTER_CV, "page:1:block:3"),
    )

    assert fact.model_dump(mode="json")["metrics"] == [{"value": 12, "unit": "%", "label": "synthetic improvement"}]
    assert company.is_claim_usable is True
    assert title.is_claim_usable is date.is_claim_usable is False

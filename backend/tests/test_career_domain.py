from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.career import (
    CareerFact,
    CareerProfile,
    Education,
    FactSource,
    LanguageSkill,
    Metric,
    SourceType,
    VerificationStatus,
    WorkExperience,
)


def master_cv_source() -> FactSource:
    return FactSource(
        source_type=SourceType.MASTER_CV,
        reference="experience_2_bullet_3",
        original_text="Reduced setup time by 18%.",
    )


def verified_fact() -> CareerFact:
    return CareerFact(
        statement="Reduced setup time by 18%.",
        verification_status=VerificationStatus.VERIFIED,
        source=master_cv_source(),
        metrics=(Metric(value=18, unit="%", label="setup time reduction"),),
        action="Reduced",
        object="setup time",
    )


def test_verified_career_fact_is_usable() -> None:
    fact = verified_fact()

    assert fact.is_claim_usable is True


def test_user_provided_career_fact_is_usable() -> None:
    fact = CareerFact(
        statement="Led commissioning activities.",
        verification_status=VerificationStatus.USER_PROVIDED,
        source=FactSource(source_type=SourceType.USER_INPUT, reference="coach_answer_1"),
    )

    assert fact.is_claim_usable is True


def test_inferred_unverified_fact_is_not_usable() -> None:
    fact = CareerFact(
        statement="May have supervised a team.",
        verification_status=VerificationStatus.INFERRED_UNVERIFIED,
        source=FactSource(source_type=SourceType.SYSTEM_INFERENCE, reference="inference_1"),
    )

    assert fact.is_claim_usable is False


def test_empty_fact_statement_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CareerFact(
            statement="   ",
            verification_status=VerificationStatus.VERIFIED,
            source=master_cv_source(),
        )


def test_provenance_is_preserved_during_serialization() -> None:
    serialized = verified_fact().model_dump(mode="json")

    assert serialized["source"] == {
        "source_type": "master_cv",
        "reference": "experience_2_bullet_3",
        "original_text": "Reduced setup time by 18%.",
    }


def test_metric_serializes_to_json_compatible_data() -> None:
    serialized = Metric(value=7, unit="people", label="team size").model_dump(mode="json")

    assert serialized == {"value": 7, "unit": "people", "label": "team size"}


def test_current_work_experience_can_omit_end_date() -> None:
    experience = WorkExperience(
        company="Repcon",
        title="Commissioning Engineer",
        start_date=date(2024, 1, 1),
        is_current=True,
    )

    assert experience.end_date is None


def test_current_work_experience_cannot_have_end_date() -> None:
    with pytest.raises(ValidationError):
        WorkExperience(
            company="Repcon",
            title="Commissioning Engineer",
            start_date=date(2024, 1, 1),
            end_date=date(2025, 1, 1),
            is_current=True,
        )


def test_past_work_experience_requires_end_date() -> None:
    with pytest.raises(ValidationError):
        WorkExperience(
            company="Repcon",
            title="Commissioning Engineer",
            start_date=date(2024, 1, 1),
        )


def test_past_work_experience_with_end_date_is_valid() -> None:
    experience = WorkExperience(
        company="Repcon",
        title="Commissioning Engineer",
        start_date=date(2022, 1, 1),
        end_date=date(2023, 12, 31),
    )

    assert experience.is_current is False


def test_profile_with_experiences_and_education_serializes() -> None:
    profile = CareerProfile(
        full_name="İlana Özel",
        work_experiences=(
            WorkExperience(
                company="Repcon",
                title="Commissioning Engineer",
                start_date=date(2022, 1, 1),
                end_date=date(2023, 12, 31),
                facts=(verified_fact(),),
            ),
            WorkExperience(
                company="Feyz Automation",
                title="Automation Engineer",
                start_date=date(2024, 1, 1),
                is_current=True,
            ),
        ),
        education=(
            Education(
                institution="İstanbul Teknik Üniversitesi",
                degree="Bachelor's degree",
                field_of_study="Electrical Engineering",
            ),
        ),
    )

    serialized = profile.model_dump(mode="json")

    assert len(serialized["work_experiences"]) == 2
    assert serialized["education"][0]["institution"] == "İstanbul Teknik Üniversitesi"
    assert serialized["work_experiences"][0]["facts"][0]["metrics"][0]["value"] == 18


def test_profile_sections_can_be_empty() -> None:
    profile = CareerProfile()

    assert profile.model_dump(mode="json") == {
        "full_name": None,
        "headline": None,
        "contact": None,
        "summary_facts": [],
        "work_experiences": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "languages": [],
        "projects": [],
        "publications": [],
        "additional_facts": [],
    }


def test_multiple_languages_are_independent() -> None:
    source = FactSource(source_type=SourceType.USER_INPUT, reference="profile_form")
    profile = CareerProfile(
        languages=(
            LanguageSkill(language="Turkish", proficiency="Native", source=source),
            LanguageSkill(language="English", proficiency="Professional", source=source),
        )
    )

    assert [language.language for language in profile.languages] == ["Turkish", "English"]


def test_user_provided_turkish_text_is_preserved() -> None:
    statement = "Uluslararası devreye alma faaliyetlerini yönettim."
    fact = CareerFact(
        statement=statement,
        verification_status=VerificationStatus.USER_PROVIDED,
        source=FactSource(source_type=SourceType.USER_INPUT, reference="coach_answer_2"),
    )

    assert fact.statement == statement


def test_source_original_text_preserves_unicode() -> None:
    original_text = "Kurulum süresini %18 azalttım — ölçüm doğrulandı."
    source = FactSource(
        source_type=SourceType.MASTER_CV,
        reference="deneyim_2_madde_3",
        original_text=original_text,
    )

    assert source.model_dump(mode="json")["original_text"] == original_text

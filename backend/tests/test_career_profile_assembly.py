from app.domain.career import CareerFact, CareerProfile, FactSource, LanguageSkill, SourceType, VerificationStatus
from app.services.career_profile_assembly import assemble_verified_career_profile


def fact(
    statement: str,
    *,
    status: VerificationStatus = VerificationStatus.USER_PROVIDED,
    skills: tuple[str, ...] | None = None,
    language: str | None = None,
    proficiency: str | None = None,
    reference: str = "candidate:synthetic",
) -> CareerFact:
    return CareerFact(
        statement=statement,
        verification_status=status,
        source=FactSource(source_type=SourceType.USER_INPUT, reference=reference, original_text=statement),
        skills=(statement,) if skills is None else skills,
        language=language,
        language_proficiency=proficiency,
    )


def test_empty_facts_returns_an_equivalent_new_profile() -> None:
    base = CareerProfile(skills=(fact("Python", status=VerificationStatus.VERIFIED),))

    result = assemble_verified_career_profile(base, ())

    assert result.profile == base
    assert result.profile is not base
    assert result.applied_facts == result.skipped_facts == result.conflicts == ()


def test_verified_and_user_provided_skills_are_applied_with_provenance() -> None:
    verified = fact("Python", status=VerificationStatus.VERIFIED, reference="page:1:block:1")
    confirmed = fact("Excel", reference="candidate:1:accept")

    result = assemble_verified_career_profile(CareerProfile(), (confirmed, verified))

    assert [item.statement for item in result.profile.skills] == ["Excel", "Python"]
    assert result.applied_facts == (confirmed, verified)
    assert result.profile.skills[0].source.reference == "candidate:1:accept"
    assert result.profile.skills[1].source.reference == "page:1:block:1"


def test_unverified_fact_never_enters_the_profile() -> None:
    unverified = fact("Python", status=VerificationStatus.INFERRED_UNVERIFIED)

    result = assemble_verified_career_profile(CareerProfile(), (unverified,))

    assert result.profile.skills == ()
    assert result.skipped_facts[0].reason_code == "untrusted_verification_status"
    assert unverified.is_claim_usable is False


def test_duplicate_skills_are_skipped_but_distinct_strengthened_names_are_not_merged() -> None:
    base = CareerProfile(skills=(fact("Excel", status=VerificationStatus.VERIFIED), fact("SAP", status=VerificationStatus.VERIFIED)))
    duplicate = fact(" excel ", reference="candidate:duplicate")
    advanced_excel = fact("Advanced Excel", reference="candidate:advanced")
    sap_erp = fact("SAP ERP", reference="candidate:sap-erp")

    result = assemble_verified_career_profile(base, (duplicate, advanced_excel, sap_erp))

    assert [item.statement for item in result.profile.skills] == ["Excel", "SAP", "Advanced Excel", "SAP ERP"]
    assert len(result.skipped_facts) == 1
    assert result.skipped_facts[0].fact == duplicate
    assert result.skipped_facts[0].reason_code == "duplicate_skill"


def test_unsupported_structured_categories_are_preserved_as_skipped_without_guessing() -> None:
    ambiguous = fact("Production Engineer at Example Manufacturing", skills=())

    result = assemble_verified_career_profile(CareerProfile(), (ambiguous,))

    assert result.profile.work_experiences == result.profile.education == ()
    assert result.skipped_facts[0].fact == ambiguous
    assert result.skipped_facts[0].reason_code == "unsupported_fact_mapping"


def test_conflicting_explicit_language_proficiency_is_surfaced_without_overwrite() -> None:
    base = CareerProfile(
        languages=(
            LanguageSkill(
                language="English",
                proficiency="B2",
                source=FactSource(source_type=SourceType.MASTER_CV, reference="page:1:block:1", original_text="English - B2"),
            ),
        )
    )
    incoming = fact("English", skills=(), language="English", proficiency="C1", reference="candidate:language")

    result = assemble_verified_career_profile(base, (incoming,))

    assert result.profile.languages == base.languages
    assert result.skipped_facts[0].reason_code == "conflicting_language_proficiency"
    assert result.conflicts[0].target_category == "language"
    assert result.conflicts[0].reason_code == "conflicting_language_proficiency"
    assert result.conflicts[0].incoming_source == incoming.source


def test_matching_explicit_language_proficiency_is_deduplicated() -> None:
    base = CareerProfile(
        languages=(
            LanguageSkill(
                language="English",
                proficiency="B2",
                source=FactSource(source_type=SourceType.MASTER_CV, reference="page:1:block:1", original_text="English - B2"),
            ),
        )
    )
    incoming = fact("English", skills=(), language=" english ", proficiency=" b2 ")

    result = assemble_verified_career_profile(base, (incoming,))

    assert result.profile.languages == base.languages
    assert result.skipped_facts[0].reason_code == "duplicate_language"
    assert result.conflicts == ()


def test_assembly_does_not_mutate_inputs_and_is_order_independent_for_unrelated_facts() -> None:
    base = CareerProfile(skills=(fact("Python", status=VerificationStatus.VERIFIED),))
    excel = fact("Excel", reference="candidate:excel")
    sap = fact("SAP", reference="candidate:sap")

    first = assemble_verified_career_profile(base, (sap, excel))
    second = assemble_verified_career_profile(base, (excel, sap))

    assert first.profile == second.profile
    assert base.skills == (fact("Python", status=VerificationStatus.VERIFIED),)
    assert excel.statement == "Excel"
    assert sap.statement == "SAP"

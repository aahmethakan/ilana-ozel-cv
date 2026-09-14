import json
import unicodedata
from collections.abc import Sequence

from app.domain.career import CareerFact, CareerProfile, LanguageSkill, VerificationStatus
from app.services.career_profile_assembly.schemas import (
    CareerProfileAssemblyResult,
    ProfileAssemblyConflict,
    SkippedCareerFact,
)

_TRUSTED_STATUSES = {VerificationStatus.VERIFIED, VerificationStatus.USER_PROVIDED}


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _stable_fact_key(fact: CareerFact) -> str:
    return json.dumps(fact.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def _is_single_explicit_skill(fact: CareerFact) -> bool:
    return len(fact.skills) == 1 and _normalized(fact.skills[0]) == _normalized(fact.statement)


def _is_explicit_language(fact: CareerFact) -> bool:
    return fact.language is not None and not fact.skills


def _language_value(language: str, proficiency: str | None) -> str:
    return f"{language} ({proficiency})" if proficiency is not None else language


def assemble_verified_career_profile(
    base_profile: CareerProfile,
    confirmed_facts: Sequence[CareerFact],
) -> CareerProfileAssemblyResult:
    """Deterministically merge only explicitly trusted, safely mapped CareerFacts."""

    skills = list(base_profile.skills)
    skill_keys = {_normalized(fact.statement) for fact in skills}
    languages = list(base_profile.languages)
    languages_by_key = {_normalized(item.language): item for item in languages}
    applied: list[CareerFact] = []
    skipped: list[SkippedCareerFact] = []
    conflicts: list[ProfileAssemblyConflict] = []

    for fact in sorted(confirmed_facts, key=_stable_fact_key):
        if fact.verification_status not in _TRUSTED_STATUSES:
            skipped.append(SkippedCareerFact(fact=fact, reason_code="untrusted_verification_status"))
            continue
        if fact.language is not None and not _is_explicit_language(fact):
            skipped.append(SkippedCareerFact(fact=fact, reason_code="unsupported_fact_mapping"))
            continue
        if _is_explicit_language(fact):
            language = fact.language
            assert language is not None
            key = _normalized(language)
            existing = languages_by_key.get(key)
            if existing is not None:
                if _normalized(existing.proficiency or "") == _normalized(fact.language_proficiency or ""):
                    skipped.append(SkippedCareerFact(fact=fact, reason_code="duplicate_language"))
                else:
                    skipped.append(SkippedCareerFact(fact=fact, reason_code="conflicting_language_proficiency"))
                    conflicts.append(
                        ProfileAssemblyConflict(
                            target_category="language",
                            existing_value=_language_value(existing.language, existing.proficiency),
                            incoming_value=_language_value(language, fact.language_proficiency),
                            existing_source=existing.source,
                            incoming_source=fact.source,
                            reason_code="conflicting_language_proficiency",
                        )
                    )
                continue
            language_skill = LanguageSkill(
                language=language,
                proficiency=fact.language_proficiency,
                source=fact.source,
            )
            languages_by_key[key] = language_skill
            languages.append(language_skill)
            applied.append(fact)
            continue
        if not _is_single_explicit_skill(fact):
            skipped.append(SkippedCareerFact(fact=fact, reason_code="unsupported_fact_mapping"))
            continue

        key = _normalized(fact.skills[0])
        if key in skill_keys:
            skipped.append(SkippedCareerFact(fact=fact, reason_code="duplicate_skill"))
            continue
        skill_keys.add(key)
        skills.append(fact)
        applied.append(fact)

    profile = base_profile.model_copy(update={"skills": tuple(skills), "languages": tuple(languages)})
    return CareerProfileAssemblyResult(
        profile=profile,
        applied_facts=tuple(applied),
        skipped_facts=tuple(skipped),
        conflicts=tuple(conflicts),
    )

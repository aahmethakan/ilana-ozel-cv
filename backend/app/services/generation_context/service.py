from app.confirmation.structured.schemas import StructuredResolutionStatus
from app.domain.career import CareerFact, CareerProfile, VerificationStatus
from app.services.career_context.schemas import UnifiedCareerContext
from app.services.generation_context.schemas import EligibleAtomicClaim, EligibleContact, EligibleEducation, EligibleStructuredField, EligibleWorkExperience, GenerationContext, atomic_evidence_id, structured_field_evidence_id
from app.services.profile_readiness import ReadinessStatus, assess_unified_career_readiness
from app.services.profile_readiness.service import _is_directly_sourced


class GenerationContextNotReadyError(ValueError):
    pass


def _eligible_contact(profile: CareerProfile) -> EligibleContact | None:
    if profile.contact is None:
        return None
    contact = EligibleContact(
        email=profile.contact.email if profile.contact.email and _is_directly_sourced(profile.contact.email.source) else None,
        phone=profile.contact.phone if profile.contact.phone and _is_directly_sourced(profile.contact.phone.source) else None,
        website=profile.contact.website if profile.contact.website and _is_directly_sourced(profile.contact.website.source) else None,
    )
    return contact if any((contact.email, contact.phone, contact.website)) else None


def _atomic_claims(profile: CareerProfile) -> tuple[EligibleAtomicClaim, ...]:
    collections = (
        ("summary_fact", profile.summary_facts), ("skill", profile.skills), ("tool", profile.tools),
        ("additional_fact", profile.additional_facts),
        *(("work_fact", item.facts) for item in profile.work_experiences),
        *(("education_fact", item.facts) for item in profile.education),
        *(("project_fact", item.facts) for item in profile.projects),
    )
    claims: list[EligibleAtomicClaim] = []
    seen: set[str] = set()
    for claim_type, facts in collections:
        for fact in facts:
            if not fact.is_claim_usable:
                continue
            evidence_id = atomic_evidence_id(claim_type=claim_type, statement=fact.statement, verification_status=fact.verification_status, source=fact.source)
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            claims.append(EligibleAtomicClaim(evidence_id=evidence_id, claim_type=claim_type, statement=fact.statement, verification_status=fact.verification_status, source=fact.source))
    direct_collections = (
        ("certification", ((item.name, item.source) for item in profile.certifications)),
        ("language", ((item.language, item.source) for item in profile.languages)),
        ("publication", ((item.title, item.source) for item in profile.publications)),
    )
    for claim_type, values in direct_collections:
        for statement, source in values:
            if not _is_directly_sourced(source):
                continue
            evidence_id = atomic_evidence_id(claim_type=claim_type, statement=statement, verification_status=VerificationStatus.VERIFIED, source=source)
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            claims.append(EligibleAtomicClaim(evidence_id=evidence_id, claim_type=claim_type, statement=statement, verification_status=VerificationStatus.VERIFIED, source=source))
    return tuple(claims)


def _work_entries(context: UnifiedCareerContext) -> tuple[EligibleWorkExperience, ...]:
    result: list[EligibleWorkExperience] = []
    for entry in context.structured_assembly.profile.work_experiences:
        if entry.resolution_status is not StructuredResolutionStatus.RESOLVED:
            raise ValueError("A READY context cannot contain a partially resolved work record.")
        record = entry.record
        def field(name, value):
            return EligibleStructuredField(evidence_id=structured_field_evidence_id(record_type="work", record_id=record.record_id, candidate_id=entry.candidate_id, field_name=name, value=value), record_type="work", record_id=record.record_id, candidate_id=entry.candidate_id, field_name=name, value=value)
        result.append(EligibleWorkExperience(
            evidence_id=f"work:{record.record_id}", record_id=record.record_id, candidate_id=entry.candidate_id,
            company=field("company", record.company), title=field("title", record.title),
            location=field("location", record.location) if record.location and record.location.is_claim_usable else None,
            start_date=field("start_date", record.start_date) if record.start_date and record.start_date.is_claim_usable else None,
            end_date=field("end_date", record.end_date) if record.end_date and record.end_date.is_claim_usable else None,
            is_current=field("is_current", record.is_current) if record.is_current and record.is_current.is_claim_usable else None,
        ))
    return tuple(result)


def _education_entries(context: UnifiedCareerContext) -> tuple[EligibleEducation, ...]:
    result: list[EligibleEducation] = []
    for entry in context.structured_assembly.profile.education:
        if entry.resolution_status is not StructuredResolutionStatus.RESOLVED:
            raise ValueError("A READY context cannot contain a partially resolved education record.")
        record = entry.record
        def field(name, value):
            return EligibleStructuredField(evidence_id=structured_field_evidence_id(record_type="education", record_id=record.record_id, candidate_id=entry.candidate_id, field_name=name, value=value), record_type="education", record_id=record.record_id, candidate_id=entry.candidate_id, field_name=name, value=value)
        result.append(EligibleEducation(
            evidence_id=f"education:{record.record_id}", record_id=record.record_id, candidate_id=entry.candidate_id,
            institution=field("institution", record.institution),
            degree=field("degree", record.degree) if record.degree and record.degree.is_claim_usable else None,
            field_of_study=field("field_of_study", record.field_of_study) if record.field_of_study and record.field_of_study.is_claim_usable else None,
            start_date=field("start_date", record.start_date) if record.start_date and record.start_date.is_claim_usable else None,
            end_date=field("end_date", record.end_date) if record.end_date and record.end_date.is_claim_usable else None,
        ))
    return tuple(result)


def build_generation_context(context: UnifiedCareerContext) -> GenerationContext:
    readiness = assess_unified_career_readiness(context)
    if readiness.status is not ReadinessStatus.READY:
        raise GenerationContextNotReadyError("Generation context requires unified readiness status READY.")
    if context.structured_assembly.conflicts:
        raise ValueError("A generation context cannot include structured assembly conflicts.")
    return GenerationContext(contact=_eligible_contact(context.atomic_profile), atomic_claims=_atomic_claims(context.atomic_profile), work_experiences=_work_entries(context), education=_education_entries(context))

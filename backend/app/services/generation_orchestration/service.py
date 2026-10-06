"""Fail-closed bridge from an already-authoritative plan to rendered evidence."""

from app.services.claim_rendering import ClaimRenderingMode, render_validated_claim
from app.services.claim_validation import AtomicClaimAssertion, ClaimKind, EducationFieldAssertion, GeneratedClaimProposal, WorkFactAssociationAssertion, WorkFieldAssertion, claim_id
from app.services.generation_context import GenerationContext
from app.services.generation_orchestration.schemas import GeneratedCvDraft
from app.services.generation_strategy import GenerationPlan, GenerationTargetSection
from app.services.evidence_convergence import EducationField, WorkExperienceField
from app.services.section_composition import compose_education_entry, compose_work_entry


def _proposal(kind, text, assertion):
    return GeneratedClaimProposal(claim_id=claim_id(claim_kind=kind, text=text, assertions=(assertion,)), text=text, claim_kind=kind, assertions=(assertion,))


def generate_deterministic_cv(context: GenerationContext, plan: GenerationPlan) -> GeneratedCvDraft:
    """Validate every plan selection against context; never silently omit one."""
    skills = []
    work_facts = []
    work_targets: dict[tuple[str, str], list] = {}
    for selection in plan.selections:
        atomic = context.find_eligible_evidence(selection.atomic_evidence_id)
        if atomic is None or not hasattr(atomic, "statement"):
            raise ValueError("Generation plan references non-eligible atomic evidence.")
        if selection.target_section is GenerationTargetSection.WORK_EXPERIENCE:
            if not all((selection.association_evidence_id, selection.work_record_id, selection.work_candidate_id)):
                raise ValueError("Work selection requires complete association lineage.")
            assertion = WorkFactAssociationAssertion(association_evidence_id=selection.association_evidence_id, atomic_evidence_id=selection.atomic_evidence_id, work_record_id=selection.work_record_id, work_candidate_id=selection.work_candidate_id)
            rendered = render_validated_claim(context, _proposal(ClaimKind.EXPERIENCE_BULLET, atomic.statement, assertion), ClaimRenderingMode.WORK_FACT_EXACT)
            work_facts.append(rendered)
            work_targets.setdefault((selection.work_record_id, selection.work_candidate_id), []).append(rendered)
        elif selection.target_section is GenerationTargetSection.SKILLS:
            assertion = AtomicClaimAssertion(evidence_id=selection.atomic_evidence_id, claim_type=atomic.claim_type, value=atomic.statement)
            skills.append(render_validated_claim(context, _proposal(ClaimKind.SKILL, atomic.statement, assertion), ClaimRenderingMode.ATOMIC_EXACT))
        else:
            raise ValueError("Unsupported deterministic generation target.")
    if len(skills) + len(work_facts) != len(plan.selections):
        raise ValueError("Generation plan selections cannot be silently dropped.")
    entries = []
    for pair, facts in sorted(work_targets.items()):
        work = next((item for item in context.work_experiences if (item.record_id, item.candidate_id) == pair), None)
        if work is None:
            raise ValueError("Work selection target is not eligible.")
        def field_claim(value, field_name, mode):
            assertion = WorkFieldAssertion(evidence_id=value.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=field_name, value=value.value.value)
            return render_validated_claim(context, _proposal(ClaimKind.EXPERIENCE_BULLET, str(value.value.value), assertion), mode)
        identity = render_validated_claim(context, GeneratedClaimProposal(claim_id=claim_id(claim_kind=ClaimKind.EXPERIENCE_BULLET, text="identity", assertions=(WorkFieldAssertion(evidence_id=work.company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value=work.company.value.value), WorkFieldAssertion(evidence_id=work.title.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.TITLE, value=work.title.value.value))), text="identity", claim_kind=ClaimKind.EXPERIENCE_BULLET, assertions=(WorkFieldAssertion(evidence_id=work.company.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.COMPANY, value=work.company.value.value), WorkFieldAssertion(evidence_id=work.title.evidence_id, record_id=work.record_id, candidate_id=work.candidate_id, field_name=WorkExperienceField.TITLE, value=work.title.value.value))), ClaimRenderingMode.WORK_IDENTITY)
        date = field_claim(work.start_date, WorkExperienceField.START_DATE, ClaimRenderingMode.WORK_DATE) if work.start_date else None
        entries.append(compose_work_entry((identity, *( (date,) if date else ()), *facts)))
    education_entries = []
    for education in sorted(context.education, key=lambda item: (item.record_id, item.candidate_id)):
        def education_assertion(value, field_name):
            return EducationFieldAssertion(evidence_id=value.evidence_id, record_id=education.record_id, candidate_id=education.candidate_id, field_name=field_name, value=value.value.value)
        identity_values = ((education.institution, EducationField.INSTITUTION),)
        if education.degree:
            identity_values += ((education.degree, EducationField.DEGREE),)
        if education.field_of_study:
            identity_values += ((education.field_of_study, EducationField.FIELD_OF_STUDY),)
        identity_assertions = tuple(education_assertion(value, field) for value, field in identity_values)
        identity = render_validated_claim(
            context,
            GeneratedClaimProposal(
                claim_id=claim_id(claim_kind=ClaimKind.EDUCATION, text="education_identity", assertions=identity_assertions),
                text="education_identity",
                claim_kind=ClaimKind.EDUCATION,
                assertions=identity_assertions,
            ),
            ClaimRenderingMode.EDUCATION_IDENTITY,
        )
        date_values = tuple(
            (value, field)
            for value, field in ((education.start_date, EducationField.START_DATE), (education.end_date, EducationField.END_DATE))
            if value is not None
        )
        date = None
        if date_values:
            date_assertions = tuple(education_assertion(value, field) for value, field in date_values)
            date = render_validated_claim(
                context,
                GeneratedClaimProposal(
                    claim_id=claim_id(claim_kind=ClaimKind.EDUCATION, text="education_date", assertions=date_assertions),
                    text="education_date",
                    claim_kind=ClaimKind.EDUCATION,
                    assertions=date_assertions,
                ),
                ClaimRenderingMode.EDUCATION_DATE,
            )
        education_entries.append(compose_education_entry((identity, *((date,) if date else ()))))
    return GeneratedCvDraft(mode=plan.mode, plan=plan, skill_claims=tuple(sorted(skills, key=lambda item: item.rendered_claim_id)), work_fact_claims=tuple(sorted(work_facts, key=lambda item: item.rendered_claim_id)), work_entries=tuple(entries), education_entries=tuple(education_entries))

from app.services.claim_rendering import ClaimRenderingMode, RenderedClaim
from app.services.section_composition.schemas import (
    ComposedEducationEntry, ComposedSection, ComposedWorkEntry, SectionCompositionError,
    SectionCompositionErrorCode, SectionType, education_entry_id, section_id, work_entry_id,
)


def _fail(code, message): raise SectionCompositionError(code, message)

def _entry(claims, *, identity_mode, date_mode, record_type, constructor, id_factory):
    claims = tuple(claims)
    identity = [c for c in claims if c.rendering_mode is identity_mode]
    dates = [c for c in claims if c.rendering_mode is date_mode]
    if any(c.rendering_mode not in {identity_mode, date_mode} for c in claims): _fail(SectionCompositionErrorCode.UNEXPECTED_RENDERING_MODE, "Unsupported rendering mode for entry.")
    if not identity: _fail(SectionCompositionErrorCode.MISSING_IDENTITY, "Identity claim is required.")
    if len(identity) > 1 or len(dates) > 1: _fail(SectionCompositionErrorCode.DUPLICATE_SLOT, "An entry slot may appear once.")
    if len({claim.rendered_claim_id for claim in claims}) != len(claims): _fail(SectionCompositionErrorCode.DUPLICATE_CLAIM, "A claim cannot fill multiple slots.")
    chosen = tuple(identity + dates)
    lineages = [c.structured_lineage for c in chosen]
    if any(l is None or l.record_type != record_type for l in lineages): _fail(SectionCompositionErrorCode.LINEAGE_MISMATCH, "Structured lineage is required.")
    if len({(l.record_id, l.candidate_id) for l in lineages}) != 1: _fail(SectionCompositionErrorCode.LINEAGE_MISMATCH, "Entry claims must share lineage.")
    lineage = lineages[0]
    date = dates[0] if dates else None
    return constructor(entry_id=id_factory(lineage.record_id, lineage.candidate_id, identity[0].rendered_claim_id, date.rendered_claim_id if date else None), record_id=lineage.record_id, candidate_id=lineage.candidate_id, identity_claim=identity[0], date_claim=date)

def compose_work_entry(claims): return _entry(claims, identity_mode=ClaimRenderingMode.WORK_IDENTITY, date_mode=ClaimRenderingMode.WORK_DATE, record_type="work", constructor=ComposedWorkEntry, id_factory=work_entry_id)
def compose_education_entry(claims): return _entry(claims, identity_mode=ClaimRenderingMode.EDUCATION_IDENTITY, date_mode=ClaimRenderingMode.EDUCATION_DATE, record_type="education", constructor=ComposedEducationEntry, id_factory=education_entry_id)

def _section(entries, section_type, entry_type):
    entries = tuple(entries)
    if not entries or not all(isinstance(e, entry_type) for e in entries): _fail(SectionCompositionErrorCode.SECTION_TYPE_MISMATCH, "Section entries have an incompatible type.")
    if len({e.entry_id for e in entries}) != len(entries): _fail(SectionCompositionErrorCode.DUPLICATE_ENTRY, "Section cannot reuse an entry.")
    claims = [c.rendered_claim_id for e in entries for c in (e.identity_claim, e.date_claim) if c]
    if len(set(claims)) != len(claims): _fail(SectionCompositionErrorCode.DUPLICATE_CLAIM, "Section cannot reuse a rendered claim.")
    return ComposedSection(section_id=section_id(section_type, tuple(e.entry_id for e in entries)), section_type=section_type, entries=entries)

def compose_work_section(entries): return _section(entries, SectionType.WORK_EXPERIENCE, ComposedWorkEntry)
def compose_education_section(entries): return _section(entries, SectionType.EDUCATION, ComposedEducationEntry)

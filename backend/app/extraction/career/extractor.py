import re

from app.domain.career import (
    CareerFact,
    CareerProfile,
    Certification,
    ContactInfo,
    ContactValue,
    FactSource,
    LanguageSkill,
    Project,
    Publication,
    SourceType,
    VerificationStatus,
)
from app.domain.document import BlockType, CVDocument, CVSection, DocumentBlock, SectionType
from app.extraction.career.result import CareerExtractionResult, UnresolvedEvidence

_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
_URL_PATTERN = re.compile(r"\b(?:https?://|www\.|(?:www\.)?linkedin\.com/)[^\s,;]+", re.I)
_BULLET_PREFIX = re.compile(r"^\s*(?:[•‣◦⁃∙\-*–—]|[\ue000-\uf8ff])\s*")
_LANGUAGE_ENTRY = re.compile(r"^\s*(?P<language>[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{1,39})\s*(?:[-:–—]\s*(?P<proficiency>[^\n]{1,60}))?\s*$")
_KNOWN_BARE_LANGUAGES = {
    "english", "turkish", "türkçe", "german", "deutsch", "french", "spanish", "italian",
    "russian", "arabic", "chinese", "japanese", "korean", "portuguese", "dutch",
}
_NARRATIVE_MARKERS = {"and", "with", "experience", "experienced", "knowledge", "using", "in", "ve", "ile"}


def _source(block: DocumentBlock) -> FactSource:
    return FactSource(
        source_type=SourceType.MASTER_CV,
        reference=block.stable_reference,
        original_text=block.raw_text,
    )


def _content_blocks(section: CVSection, blocks: dict[str, DocumentBlock]) -> tuple[DocumentBlock, ...]:
    result: list[DocumentBlock] = []
    for reference in section.block_references:
        block = blocks[reference]
        if section.original_heading and block.raw_text.strip() == section.original_heading.strip():
            continue
        result.append(block)
    return tuple(result)


def _unresolved(block: DocumentBlock, section_type: SectionType | None, reason: str) -> UnresolvedEvidence:
    return UnresolvedEvidence(block_reference=block.stable_reference, section_type=section_type, reason=reason)


def _clean_entry(text: str) -> str | None:
    value = _BULLET_PREFIX.sub("", text).strip()
    if not value or "\n" in value or len(value) > 160:
        return None
    return value


def _skill_entries(block: DocumentBlock) -> tuple[str, ...]:
    text = _BULLET_PREFIX.sub("", block.raw_text).strip()
    if not text or "\n" in text:
        return ()
    if block.block_type is BlockType.BULLET:
        return (text,)
    if "," not in text and ";" not in text:
        return ()
    if any(marker in text for marker in ".!?:"):
        return ()
    entries = tuple(part.strip() for part in re.split(r"[,;]", text) if part.strip())
    if not entries or any(len(entry.split()) > 4 for entry in entries):
        return ()
    if any(set(entry.casefold().split()) & _NARRATIVE_MARKERS for entry in entries):
        return ()
    return entries


def _language_entry(block: DocumentBlock) -> tuple[str, str | None] | None:
    text = _clean_entry(block.raw_text)
    if text is None:
        return None
    match = _LANGUAGE_ENTRY.fullmatch(text)
    if match is None:
        return None
    language = match["language"].strip()
    proficiency = match["proficiency"].strip() if match["proficiency"] else None
    if proficiency is None and language.casefold() not in _KNOWN_BARE_LANGUAGES:
        return None
    return language, proficiency


def _simple_section_entries(
    section: CVSection, blocks: dict[str, DocumentBlock], unresolved: list[UnresolvedEvidence]
) -> tuple[DocumentBlock, ...]:
    entries: list[DocumentBlock] = []
    for block in _content_blocks(section, blocks):
        if _clean_entry(block.raw_text) is None:
            unresolved.append(_unresolved(block, section.section_type, "not_a_simple_section_entry"))
        else:
            entries.append(block)
    return tuple(entries)


def extract_career_profile(document: CVDocument) -> CareerExtractionResult:
    """Extract only directly supported career data and retain all unresolved evidence."""

    blocks = {block.stable_reference: block for block in document.blocks}
    unresolved: list[UnresolvedEvidence] = []
    contact_blocks = [block for block in document.blocks if block.block_type is BlockType.CONTACT]
    sections_by_type: dict[SectionType, list[CVSection]] = {}
    for section in document.sections:
        sections_by_type.setdefault(section.section_type, []).append(section)
        if section.section_type is SectionType.CONTACT:
            contact_blocks.extend(_content_blocks(section, blocks))

    email: ContactValue | None = None
    phone: ContactValue | None = None
    website: ContactValue | None = None
    seen_contact_refs: set[str] = set()
    for block in contact_blocks:
        if block.stable_reference in seen_contact_refs:
            continue
        seen_contact_refs.add(block.stable_reference)
        source = _source(block)
        found = False
        for name, pattern in (("email", _EMAIL_PATTERN), ("phone", _PHONE_PATTERN), ("website", _URL_PATTERN)):
            match = pattern.search(block.raw_text)
            if match is None:
                continue
            found = True
            value = ContactValue(value=match.group(0), source=source)
            if name == "email" and email is None:
                email = value
            elif name == "phone" and phone is None:
                phone = value
            elif name == "website" and website is None:
                website = value
            else:
                unresolved.append(_unresolved(block, SectionType.CONTACT, "additional_contact_value"))
        if not found:
            unresolved.append(_unresolved(block, SectionType.CONTACT, "unrecognized_contact_content"))

    skills: list[CareerFact] = []
    for section in sections_by_type.get(SectionType.SKILLS, []):
        for block in _content_blocks(section, blocks):
            entries = _skill_entries(block)
            if not entries:
                unresolved.append(_unresolved(block, SectionType.SKILLS, "ambiguous_skill_content"))
                continue
            for entry in entries:
                skills.append(CareerFact(statement=entry, verification_status=VerificationStatus.VERIFIED, source=_source(block), skills=(entry,)))

    languages: list[LanguageSkill] = []
    for section in sections_by_type.get(SectionType.LANGUAGES, []):
        for block in _content_blocks(section, blocks):
            entry = _language_entry(block)
            if entry is None:
                unresolved.append(_unresolved(block, SectionType.LANGUAGES, "ambiguous_language_content"))
                continue
            languages.append(LanguageSkill(language=entry[0], proficiency=entry[1], source=_source(block)))

    certifications: list[Certification] = []
    for section in sections_by_type.get(SectionType.CERTIFICATIONS, []):
        for block in _simple_section_entries(section, blocks, unresolved):
            certifications.append(Certification(name=_clean_entry(block.raw_text) or block.raw_text, source=_source(block)))

    projects: list[Project] = []
    for section in sections_by_type.get(SectionType.PROJECTS, []):
        for block in _simple_section_entries(section, blocks, unresolved):
            name = _clean_entry(block.raw_text) or block.raw_text
            projects.append(Project(name=name, facts=(CareerFact(statement=name, verification_status=VerificationStatus.VERIFIED, source=_source(block)),)))

    publications: list[Publication] = []
    for section in sections_by_type.get(SectionType.PUBLICATIONS, []):
        for block in _simple_section_entries(section, blocks, unresolved):
            publications.append(Publication(title=_clean_entry(block.raw_text) or block.raw_text, source=_source(block)))

    for section_type, reason in ((SectionType.EXPERIENCE, "ambiguous_experience_content"), (SectionType.EDUCATION, "ambiguous_education_content")):
        for section in sections_by_type.get(section_type, []):
            unresolved.extend(_unresolved(block, section_type, reason) for block in _content_blocks(section, blocks))

    contact = ContactInfo(email=email, phone=phone, website=website) if any((email, phone, website)) else None
    return CareerExtractionResult(profile=CareerProfile(contact=contact, skills=tuple(skills), languages=tuple(languages), certifications=tuple(certifications), projects=tuple(projects), publications=tuple(publications)), unresolved_evidence=tuple(unresolved))

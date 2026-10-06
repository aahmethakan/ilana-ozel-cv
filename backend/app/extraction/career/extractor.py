import re

from app.domain.career import (
    CareerDate, CareerFact, CareerProfile, Certification, ContactInfo, ContactValue,
    CandidateIdentity, Education, FactSource, LanguageSkill, Metric, Project, Publication,
    ProvenancedText, ProvenancedCareerDate, ProvenancedBool, SourceType, VerificationStatus, WorkExperience,
)
from app.domain.document import BlockType, CVDocument, CVSection, DocumentBlock, IdentityField, ParserConfidence, SectionType
from app.extraction.career.dates import ParsedDateRange, parse_date_range
from app.extraction.career.result import CareerExtractionResult, UnresolvedEvidence
from app.confirmation.structured import StructuredRecordOrigin, create_work_experience_candidate

_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
_URL_PATTERN = re.compile(r"\b(?:https?://|www\.|(?:www\.)?linkedin\.com/)[^\s,;]+", re.I)
_BULLET_PREFIX = re.compile(r"^\s*(?:[•‣◦⁃∙\-*–—]|[\ue000-\uf8ff])\s*")
_LANGUAGE_ENTRY = re.compile(r"^\s*(?P<language>[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{1,39})\s*(?:[-:–—]\s*(?P<proficiency>[^\n]{1,60}))?\s*$")
_KNOWN_BARE_LANGUAGES = {"english", "turkish", "türkçe", "german", "deutsch", "french", "spanish", "italian", "russian", "arabic", "chinese", "japanese", "korean", "portuguese", "dutch"}
_NARRATIVE_MARKERS = {"and", "with", "experience", "experienced", "knowledge", "using", "in", "ve", "ile"}
_INSTITUTION_MARKERS = ("univer", "college", "institute", "school", "faculty", "academy", "üniversit", "fakülte", "enstitü")
# A project entity needs an explicit label boundary.  A responsibility such as
# "Project follow-up" or "working on projects" is not a project name.
_PROJECT_LABEL = re.compile(r"^(?:managed\s+)?projects?\s*:\s*(?P<name>.+)$", re.I)
_PARENTHESIZED_DATE = re.compile(r"\((?P<value>[^()]{3,80})\)")
# Some PDF producers flatten a whole role or project heading into one text
# block.  These patterns deliberately require an explicit separator plus a
# parseable parenthesized date; they are not company or role inference.
_INLINE_DATED_ROLE = re.compile(
    r"(?:^|[\n\ufffd])\s*(?P<title>[^\n\ufffd()]{2,120}?)\s*[\-\u2013\u2014]\s*"
    r"(?P<company>[^\n\ufffd()]{2,120}?)\s*\((?P<date>[^()]{3,80})\)",
    re.MULTILINE,
)
_INLINE_PROJECT = re.compile(
    r"(?:^|[\n\ufffd])\s*(?P<name>[^\n\ufffd()]{2,180}?)\s*-\s*\((?P<context>[^()]{3,120})\)",
    re.MULTILINE,
)
_COMPANY_LABEL = re.compile(r"^company\s*:\s*(?P<value>.+)$", re.I)
_ROLE_LABEL = re.compile(r"^(?:role|title|position)\s*:\s*(?P<value>.+)$", re.I)
_PUBLICATION_LABEL = re.compile(r"^(?:article|publication|paper|journal)\s*[:\-–—]?\s*(?P<title>.+)$", re.I)
_PERCENT_METRIC = re.compile(r"(?<!\w)(?P<value>\d+(?:[.,]\d+)?)\s*%(?!\w)")
_UPPER_TOKEN = re.compile(r"\b[A-Z]{2,8}\b")


def _source(block: DocumentBlock) -> FactSource:
    return FactSource(source_type=SourceType.MASTER_CV, reference=block.stable_reference, original_text=block.raw_text)


def _content_blocks(section: CVSection, blocks: dict[str, DocumentBlock]) -> tuple[DocumentBlock, ...]:
    return tuple(blocks[reference] for reference in section.block_references if not (section.original_heading and blocks[reference].raw_text.strip() == section.original_heading.strip()))


def _unresolved(block: DocumentBlock, section_type: SectionType | None, reason: str) -> UnresolvedEvidence:
    return UnresolvedEvidence(block_reference=block.stable_reference, section_type=section_type, reason=reason)


def _identity_value(document: CVDocument, field: IdentityField, blocks: dict[str, DocumentBlock], unresolved: list[UnresolvedEvidence]) -> ProvenancedText | None:
    candidates = [item for item in document.identity_evidence if item.field is field]
    verified = [item for item in candidates if item.confidence is ParserConfidence.HIGH]
    values = {item.value.casefold() for item in verified}
    if len(verified) == 1 and len(values) == 1:
        item = verified[0]
        return ProvenancedText(value=item.value, verification_status=VerificationStatus.VERIFIED, value_source=_source(blocks[item.block_reference]))
    for item in candidates:
        unresolved.append(_unresolved(blocks[item.block_reference], None, f"{field.value}_{item.confidence.value}"))
    return None


def _clean_entry(text: str) -> str | None:
    value = _BULLET_PREFIX.sub("", text).strip()
    return value if value and "\n" not in value and len(value) <= 240 else None


def _skill_entries(block: DocumentBlock) -> tuple[str, ...]:
    if block.block_type is BlockType.BULLET:
        cleaned = _clean_entry(block.raw_text)
        return (cleaned,) if cleaned and cleaned not in {"\uf0b7", "\ufffd"} else ()
    # Do not run a byte-corruption-tolerant bullet regex over a whole skills
    # block: some malformed glyphs can otherwise consume the first skill.
    text = block.raw_text.strip()
    if not text:
        return ()
    # A visual one-per-line skills list is still an explicit list.  Preserve
    # the same comma/semicolon contract after normalising layout-only breaks.
    visible_lines: list[str] = []
    for line in text.splitlines():
        if line.strip().isupper() and 4 < len(line.strip()) < 80 and not line.strip().endswith((",", ";")):
            break
        visible_lines.append(line)
    text = re.sub(r"\s*\n\s*", " ", "\n".join(visible_lines))
    if "," in text or ";" in text:
        if any(marker in text for marker in ".!?:"):
            return ()
        entries = tuple(
            cleaned for part in re.split(r"[,;]", text)
            if (cleaned := part.strip().lstrip("\ufffd").strip())
        )
        return entries if entries and all(len(item.split()) <= 6 and not (set(item.casefold().split()) & _NARRATIVE_MARKERS) for item in entries) else ()
    # A short standalone list row is explicit evidence even when PDF layout lost the bullet glyph.
    if text and len(text.split()) <= 4 and not (set(text.casefold().split()) & _NARRATIVE_MARKERS) and not text.endswith((".", "!", "?", ":")):
        return (text,)
    return ()


def _language_entries(block: DocumentBlock) -> tuple[tuple[str, str | None], ...]:
    """Read explicit comma-separated language/proficiency entries in one block."""
    text = _BULLET_PREFIX.sub("", block.raw_text).strip()
    if not text:
        return ()
    entries: list[tuple[str, str | None]] = []
    for part in re.split(r"[,;\n]", text):
        value = _BULLET_PREFIX.sub("", part).strip()
        parenthesized = re.fullmatch(r"(?P<language>[A-Za-z\u00c7\u011e\u0130\u00d6\u015e\u00dc\u00e7\u011f\u0131\u00f6\u015f\u00fc][A-Za-z\u00c7\u011e\u0130\u00d6\u015e\u00dc\u00e7\u011f\u0131\u00f6\u015f\u00fc ]{1,39})\s*\((?P<proficiency>[^()\n]{1,60})\)", value)
        match = parenthesized or _LANGUAGE_ENTRY.fullmatch(value)
        if match is None:
            return ()
        language = match["language"].strip()
        proficiency = match["proficiency"].strip() if match["proficiency"] else None
        if proficiency is None and language.casefold() not in _KNOWN_BARE_LANGUAGES:
            return ()
        entries.append((language, proficiency))
    return tuple(entries)


def _lines(document: CVDocument) -> tuple[tuple[str, DocumentBlock], ...]:
    output: list[tuple[str, DocumentBlock]] = []
    for block in document.blocks:
        if block.block_type is BlockType.UNKNOWN:
            continue
        if block.block_type is BlockType.BULLET:
            output.append((block.raw_text.strip(), block))
        else:
            output.extend((line.strip(), block) for line in block.raw_text.splitlines() if line.strip())
    return tuple(output)


def _career_date(value: object) -> CareerDate:
    return CareerDate(year=value.year, month=value.month)


def _is_heading(text: str) -> bool:
    return text.isupper() and len(text) < 80 and not parse_date_range(text)


def _institution(text: str) -> bool:
    value = text.casefold()
    return any(marker in value for marker in _INSTITUTION_MARKERS)


def _metric_fact(text: str, block: DocumentBlock) -> CareerFact:
    metrics = tuple(Metric(value=float(match["value"].replace(",", ".")) if "." in match["value"] or "," in match["value"] else int(match["value"]), unit="%") for match in _PERCENT_METRIC.finditer(text))
    tools = tuple(dict.fromkeys(_UPPER_TOKEN.findall(text)))
    return CareerFact(statement=text, verification_status=VerificationStatus.VERIFIED, source=_source(block), tools=tools, metrics=metrics)


def _split_title_company(items: list[tuple[str, DocumentBlock]]) -> tuple[str, str, int] | None:
    if not items:
        return None
    labelled: dict[str, str] = {}
    for text, _ in items[:3]:
        if match := _COMPANY_LABEL.fullmatch(_BULLET_PREFIX.sub("", text).strip()):
            labelled["company"] = match["value"].strip()
        if match := _ROLE_LABEL.fullmatch(_BULLET_PREFIX.sub("", text).strip()):
            labelled["title"] = match["value"].strip()
    if labelled.get("title") and labelled.get("company"):
        return labelled["title"], labelled["company"], len(items[:2])
    first = _BULLET_PREFIX.sub("", items[0][0]).strip()
    if "," in first:
        left, right = (part.strip() for part in first.rsplit(",", 1))
        if left and right:
            return left, right, 1
        if left and len(items) > 1:
            return left, _BULLET_PREFIX.sub("", items[1][0]).strip(), 2
    if len(items) >= 2:
        title, company = (_BULLET_PREFIX.sub("", value[0]).strip() for value in items[:2])
        if title and company and not _institution(company):
            return title, company, 2
    return None


def _education_identity(items: list[tuple[str, DocumentBlock]]) -> tuple[str, str | None, DocumentBlock] | None:
    for text, block in items[:3]:
        if "," in text:
            left, right = (part.strip() for part in text.rsplit(",", 1))
            if left and right and _institution(right):
                return right, left, block
        if _institution(text):
            field = next((candidate for candidate, _ in items[:3] if candidate != text and not _PROJECT_LABEL.match(candidate)), None)
            return text, field, block
    return None


def _record_identity_before_date(
    lines: tuple[tuple[str, DocumentBlock], ...], start_index: int, date_index: int
) -> tuple[str, str, int] | None:
    """Read an explicit title/company pair immediately preceding a date anchor.

    This deliberately relies on document order, rather than company/name guessing.
    The next date or heading is the hard record boundary, so facts from a previous
    role cannot become the identity of the current role.
    """
    candidates = [item for item in lines[start_index:date_index] if item[1].block_type is not BlockType.BULLET]
    return _split_title_company(candidates[-2:])


def _inline_section_records(document: CVDocument) -> tuple[tuple[WorkExperience, ...], tuple[Education, ...], tuple[Project, ...], set[str]]:
    """Promote only self-contained records flattened inside a recognized section.

    The parser has already established section membership.  Each role/project
    below still needs its own printed title and parenthesized date/context, so
    this is a layout recovery step rather than inference from nearby prose.
    """
    blocks = {block.stable_reference: block for block in document.blocks}
    work: list[WorkExperience] = []
    education: list[Education] = []
    projects: list[Project] = []
    consumed: set[str] = set()
    for section in document.sections:
        content = _content_blocks(section, blocks)
        if section.section_type is SectionType.EXPERIENCE:
            for block in content:
                matches = tuple(_INLINE_DATED_ROLE.finditer(block.raw_text))
                for ordinal, match in enumerate(matches):
                    parsed = parse_date_range(match["date"].strip())
                    if parsed is None:
                        continue
                    title, company = match["title"].strip(), match["company"].strip()
                    if not title or not company:
                        continue
                    end = matches[ordinal + 1].start() if ordinal + 1 < len(matches) else len(block.raw_text)
                    body = block.raw_text[match.end():end]
                    facts = tuple(
                        _metric_fact(cleaned, block)
                        for item in re.split(r"[\n\ufffd]", body)
                        if (cleaned := _BULLET_PREFIX.sub("", item).strip()) and len(cleaned) <= 1000
                    )
                    work.append(WorkExperience(
                        company=company, title=title, start_date=_career_date(parsed.start),
                        end_date=_career_date(parsed.end) if parsed.end else None,
                        is_current=parsed.is_current, date_range_open=parsed.is_open_ended, facts=facts,
                    ))
                    consumed.add(block.stable_reference)
        elif section.section_type is SectionType.EDUCATION:
            for block in content:
                lines = tuple(line.strip().lstrip(":").strip() for line in block.raw_text.splitlines() if line.strip())
                values: dict[str, str] = {}
                for index, line in enumerate(lines[:-1]):
                    label = line.casefold().rstrip(":")
                    if label in {"university", "department", "high school"}:
                        values[label] = lines[index + 1]
                university = values.get("university")
                department = values.get("department")
                high_school = values.get("high school")
                if university:
                    date_match = _PARENTHESIZED_DATE.search(department or "")
                    parsed = parse_date_range(date_match["value"]) if date_match else None
                    field = _PARENTHESIZED_DATE.sub("", department or "").strip(" ,") or None
                    education.append(Education(
                        institution=university, field_of_study=field,
                        start_date=_career_date(parsed.start) if parsed else None,
                        end_date=_career_date(parsed.end) if parsed and parsed.end else None,
                    ))
                    consumed.add(block.stable_reference)
                if high_school:
                    date_match = _PARENTHESIZED_DATE.search(high_school)
                    parsed = parse_date_range(date_match["value"]) if date_match else None
                    institution = _PARENTHESIZED_DATE.sub("", high_school).strip(" ,")
                    education.append(Education(
                        institution=institution,
                        start_date=_career_date(parsed.start) if parsed else None,
                        end_date=_career_date(parsed.end) if parsed and parsed.end else None,
                    ))
                    consumed.add(block.stable_reference)
        elif section.section_type is SectionType.PROJECTS:
            for block in content:
                for match in _INLINE_PROJECT.finditer(block.raw_text):
                    name = match["name"].strip()
                    if name:
                        projects.append(Project(name=name, facts=(CareerFact(
                            statement=name, verification_status=VerificationStatus.VERIFIED, source=_source(block),
                        ),)))
                        consumed.add(block.stable_reference)
    return tuple(work), tuple(education), tuple(projects), consumed


def _structured_records(document: CVDocument) -> tuple[tuple[WorkExperience, ...], tuple[Education, ...], tuple[Project, ...], tuple, set[str]]:
    lines = _lines(document)
    starts = [(index, parsed) for index, (text, _) in enumerate(lines) if (parsed := parse_date_range(text)) is not None]
    work: list[WorkExperience] = []
    education: list[Education] = []
    projects: list[Project] = []
    partials: list = []
    consumed: set[str] = set()
    for ordinal, (start_index, parsed) in enumerate(starts):
        end_index = starts[ordinal + 1][0] if ordinal + 1 < len(starts) else len(lines)
        candidates: list[tuple[str, DocumentBlock]] = []
        for text, block in lines[start_index + 1:end_index]:
            if block.block_type is BlockType.HEADING:
                break
            candidates.append((text, block))
        if not candidates:
            continue
        education_identity = _education_identity(candidates)
        if education_identity is not None:
            institution_text, field, institution_block = education_identity
            education.append(Education(institution=institution_text, field_of_study=field, start_date=_career_date(parsed.start), end_date=_career_date(parsed.end) if parsed.end else None))
            consumed.update({lines[start_index][1].stable_reference, institution_block.stable_reference})
            continue
        # PDFs commonly place the date either before or after the role header.
        # Use the following pair first; if this range starts with bullets, only
        # the immediately preceding non-bullet pair may identify the role.
        identity_result = None if candidates and candidates[0][1].block_type is BlockType.BULLET else _split_title_company(candidates)
        identity_used = identity_result[2] if identity_result is not None else 0
        identity_references: set[str] = set()
        if identity_result is None and candidates and candidates[0][1].block_type is BlockType.BULLET:
            boundary = max(
                (index + 1 for index, (_, block) in enumerate(lines[:start_index]) if block.block_type is BlockType.HEADING),
                default=0,
            )
            before_start = boundary if ordinal == 0 else starts[ordinal - 1][0] + 1
            before_items = [item for item in lines[before_start:start_index] if item[1].block_type is not BlockType.BULLET]
            identity_result = _split_title_company(before_items[-2:])
            if identity_result is not None:
                identity_references.update(block.stable_reference for _, block in before_items[-identity_result[2]:])
        if identity_result is None:
            # A title immediately preceding a date followed by bullets is a
            # server-observed partial role, not evidence that it shares the
            # previous role's company.
            if candidates and candidates[0][1].block_type is BlockType.BULLET:
                before_start = starts[ordinal - 1][0] + 1 if ordinal else 0
                before_items = [item for item in lines[before_start:start_index] if item[1].block_type is not BlockType.BULLET]
                if len(before_items) == 1:
                    title_text, title_block = before_items[0]
                    partial_items = candidates
                    # The next role header is sometimes emitted at the end of
                    # this date-delimited range.  It is evidence for the next
                    # partial record, never for this one.
                    if ordinal + 1 < len(starts):
                        next_date_index = starts[ordinal + 1][0]
                        if next_date_index + 1 < len(lines) and lines[next_date_index + 1][1].block_type is BlockType.BULLET:
                            trailing_header = 0
                            for _, block in reversed(partial_items):
                                if block.block_type is BlockType.BULLET:
                                    break
                                trailing_header += 1
                            if trailing_header == 1:
                                partial_items = partial_items[:-1]
                    fact_sources = tuple(_source(block) for _, block in [*before_items, *partial_items])
                    partials.append(create_work_experience_candidate(
                        origin=StructuredRecordOrigin(evidence_sources=fact_sources),
                        title=ProvenancedText(value=title_text, verification_status=VerificationStatus.VERIFIED, value_source=_source(title_block)),
                        start_date=ProvenancedCareerDate(value=_career_date(parsed.start), verification_status=VerificationStatus.VERIFIED, value_source=_source(lines[start_index][1])),
                        end_date=ProvenancedCareerDate(value=_career_date(parsed.end), verification_status=VerificationStatus.VERIFIED, value_source=_source(lines[start_index][1])) if parsed.end else None,
                        is_current=ProvenancedBool(value=parsed.is_current, verification_status=VerificationStatus.VERIFIED, value_source=_source(lines[start_index][1])),
                    ))
                    consumed.update(block.stable_reference for _, block in [*before_items, *candidates])
            continue
        title, company, used = identity_result
        facts: list[CareerFact] = []
        fact_candidates = candidates[identity_used:]
        # In title/company -> date layouts, the next role header appears at the
        # end of this date-delimited range.  It belongs to the next date anchor,
        # not to the preceding role's facts.  Only remove a contiguous explicit
        # two-line header when the next anchor is followed by bullets.
        if ordinal + 1 < len(starts):
            next_date_index = starts[ordinal + 1][0]
            if next_date_index + 1 < len(lines) and lines[next_date_index + 1][1].block_type is BlockType.BULLET:
                trailing_header = 0
                for _, block in reversed(fact_candidates):
                    if block.block_type is BlockType.BULLET:
                        break
                    trailing_header += 1
                if 1 <= trailing_header <= 2:
                    fact_candidates = fact_candidates[:-trailing_header]
        for text, block in fact_candidates:
            cleaned = _BULLET_PREFIX.sub("", text).strip() if block.block_type is BlockType.BULLET else _clean_entry(text)
            if cleaned is None or _is_heading(cleaned):
                continue
            project = _PROJECT_LABEL.fullmatch(cleaned)
            if project is not None:
                name = project["name"].strip()
                if name:
                    projects.append(Project(name=name, facts=(CareerFact(statement=name, verification_status=VerificationStatus.VERIFIED, source=_source(block)),)))
            facts.append(_metric_fact(cleaned, block))
        work.append(WorkExperience(company=company, title=title, start_date=_career_date(parsed.start), end_date=_career_date(parsed.end) if parsed.end else None, is_current=parsed.is_current, date_range_open=parsed.is_open_ended, facts=tuple(facts)))
        consumed.update(block.stable_reference for _, block in lines[start_index:end_index])
        consumed.update(identity_references)
    inline_work, inline_education, inline_projects, inline_consumed = _inline_section_records(document)
    work.extend(item for item in inline_work if (item.company, item.title, item.start_date) not in {(value.company, value.title, value.start_date) for value in work})
    education.extend(item for item in inline_education if (item.institution, item.field_of_study, item.start_date) not in {(value.institution, value.field_of_study, value.start_date) for value in education})
    projects.extend(item for item in inline_projects if item.name not in {value.name for value in projects})
    consumed.update(inline_consumed)
    return tuple(work), tuple(education), tuple(projects), tuple(partials), consumed


def extract_career_profile(document: CVDocument) -> CareerExtractionResult:
    """Deterministically promote only explicit, structurally associated CV evidence."""
    blocks = {block.stable_reference: block for block in document.blocks}
    sections_by_type: dict[SectionType, list[CVSection]] = {}
    for section in document.sections:
        sections_by_type.setdefault(section.section_type, []).append(section)
    unresolved: list[UnresolvedEvidence] = []

    first_section_reference = next(
        (block.stable_reference for block in document.blocks if block.stable_reference in {reference for section in document.sections for reference in section.block_references}),
        None,
    )
    first_section_index = blocks[first_section_reference].location.block_index if first_section_reference else 6
    header_references = {
        block.stable_reference
        for block in document.blocks
        if block.location.page_number == 1 and block.location.block_index < first_section_index
    }
    # CONTACT classification is only a layout hint. A contact-looking footer or body block
    # cannot become candidate data unless it belongs to an explicit contact section.
    contact_blocks = [block for block in document.blocks if block.block_type is BlockType.CONTACT and block.stable_reference in header_references]
    for section in sections_by_type.get(SectionType.CONTACT, []):
        contact_blocks.extend(_content_blocks(section, blocks))
    values: dict[str, ContactValue | None] = {"email": None, "phone": None, "website": None}
    contact_matches: dict[str, list[tuple[str, DocumentBlock]]] = {"email": [], "phone": [], "website": []}
    seen_contact: set[str] = set()
    for block in contact_blocks:
        if block.stable_reference in seen_contact:
            continue
        seen_contact.add(block.stable_reference)
        found = False
        for name, pattern in (("email", _EMAIL_PATTERN), ("phone", _PHONE_PATTERN), ("website", _URL_PATTERN)):
            matches = tuple(pattern.finditer(block.raw_text))
            if matches:
                found = True
                contact_matches[name].extend((match.group(0), block) for match in matches)
        if not found:
            unresolved.append(_unresolved(block, SectionType.CONTACT, "unrecognized_contact_content"))
    for name, matches in contact_matches.items():
        unique = {(value.casefold(), block.stable_reference): (value, block) for value, block in matches}
        unique_values = {value.casefold() for value, _ in unique.values()}
        if len(unique_values) == 1:
            value, block = next(iter(unique.values()))
            values[name] = ContactValue(value=value, source=_source(block), verification_status=VerificationStatus.VERIFIED)
        elif unique_values:
            for _, block in unique.values():
                unresolved.append(_unresolved(block, SectionType.CONTACT, f"ambiguous_{name}"))

    skills: list[CareerFact] = []
    seen_skills: set[str] = set()
    for section in sections_by_type.get(SectionType.SKILLS, []):
        for block in _content_blocks(section, blocks):
            entries = _skill_entries(block)
            if not entries:
                # Some PDFs emit a bullet glyph as a separate block before its text block.
                # It carries layout only, not an unresolved career claim.
                if _BULLET_PREFIX.sub("", block.raw_text).strip():
                    unresolved.append(_unresolved(block, SectionType.SKILLS, "ambiguous_skill_content"))
            for entry in entries:
                key = entry.casefold()
                if key not in seen_skills:
                    seen_skills.add(key)
                    skills.append(CareerFact(statement=entry, verification_status=VerificationStatus.VERIFIED, source=_source(block), skills=(entry,)))

    languages: list[LanguageSkill] = []
    for section in sections_by_type.get(SectionType.LANGUAGES, []):
        for block in _content_blocks(section, blocks):
            entries = _language_entries(block)
            if not entries:
                unresolved.append(_unresolved(block, SectionType.LANGUAGES, "ambiguous_language_content"))
            else:
                languages.extend(LanguageSkill(language=language, proficiency=proficiency, source=_source(block)) for language, proficiency in entries)

    certifications = [Certification(name=_clean_entry(block.raw_text) or block.raw_text, source=_source(block)) for section in sections_by_type.get(SectionType.CERTIFICATIONS, []) for block in _content_blocks(section, blocks) if _clean_entry(block.raw_text)]
    projects = [Project(name=_clean_entry(block.raw_text) or block.raw_text, facts=(CareerFact(statement=_clean_entry(block.raw_text) or block.raw_text, verification_status=VerificationStatus.VERIFIED, source=_source(block)),)) for section in sections_by_type.get(SectionType.PROJECTS, []) for block in _content_blocks(section, blocks) if _clean_entry(block.raw_text) and not _INLINE_PROJECT.search(block.raw_text)]
    publications = [Publication(title=_clean_entry(block.raw_text) or block.raw_text, source=_source(block)) for section in sections_by_type.get(SectionType.PUBLICATIONS, []) for block in _content_blocks(section, blocks) if _clean_entry(block.raw_text)]
    for section in sections_by_type.get(SectionType.ADDITIONAL, []):
        for block in _content_blocks(section, blocks):
            for line in block.raw_text.splitlines():
                if match := _PUBLICATION_LABEL.fullmatch(_BULLET_PREFIX.sub("", line).strip()):
                    publications.append(Publication(title=match["title"].strip(), source=_source(block)))

    work, education, record_projects, partial_work, consumed = _structured_records(document)
    projects.extend(record_projects)
    for section_type in (SectionType.EXPERIENCE, SectionType.EDUCATION):
        for section in sections_by_type.get(section_type, []):
            for block in _content_blocks(section, blocks):
                if block.stable_reference not in consumed:
                    unresolved.append(_unresolved(block, section_type, f"ambiguous_{section_type.value}_content"))
    name = _identity_value(document, IdentityField.NAME, blocks, unresolved)
    headline = _identity_value(document, IdentityField.HEADLINE, blocks, unresolved)
    identity = CandidateIdentity(name=name, headline=headline) if name or headline else None
    contact = ContactInfo(email=values["email"], phone=values["phone"], website=values["website"]) if any(values.values()) else None
    return CareerExtractionResult(profile=CareerProfile(full_name=name.value if name else None, headline=headline.value if headline else None, identity=identity, contact=contact, work_experiences=work, education=education, skills=tuple(skills), languages=tuple(languages), certifications=tuple(certifications), projects=tuple(projects), publications=tuple(publications)), unresolved_evidence=tuple(unresolved), work_experience_candidates=partial_work)

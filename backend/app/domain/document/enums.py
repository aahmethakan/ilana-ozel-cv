from enum import StrEnum


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    BULLET = "bullet"
    CONTACT = "contact"
    UNKNOWN = "unknown"


class SectionType(StrEnum):
    CONTACT = "contact"
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    SKILLS = "skills"
    CERTIFICATIONS = "certifications"
    LANGUAGES = "languages"
    PROJECTS = "projects"
    PUBLICATIONS = "publications"
    ADDITIONAL = "additional"
    UNKNOWN = "unknown"

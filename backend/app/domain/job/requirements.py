from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RequirementCategory(StrEnum):
    SKILL = "skill"
    TOOL = "tool"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    LANGUAGE = "language"
    CERTIFICATION = "certification"
    RESPONSIBILITY = "responsibility"
    OTHER = "other"


class RequirementImportance(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    UNKNOWN = "unknown"


class RequirementExplicitness(StrEnum):
    EXPLICIT = "explicit"
    AMBIGUOUS = "ambiguous"


class JobRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    category: RequirementCategory
    text: str
    importance: RequirementImportance
    explicitness: RequirementExplicitness
    source_references: tuple[str, ...] = Field(min_length=1)
    source_texts: tuple[str, ...] = Field(min_length=1)

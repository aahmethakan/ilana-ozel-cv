from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain.career.facts import CareerFact
from app.domain.career.source import FactSource

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WorkExperience(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company: NonEmptyText
    title: NonEmptyText
    location: NonEmptyText | None = None
    start_date: date
    end_date: date | None = None
    is_current: bool = False
    facts: tuple[CareerFact, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_dates(self) -> "WorkExperience":
        if self.is_current and self.end_date is not None:
            raise ValueError("Current work experiences cannot have an end date.")
        if not self.is_current and self.end_date is None:
            raise ValueError("Past work experiences require an end date.")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("End date cannot be before start date.")
        return self


class Education(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    institution: NonEmptyText
    degree: NonEmptyText | None = None
    field_of_study: NonEmptyText | None = None
    start_date: date | None = None
    end_date: date | None = None
    facts: tuple[CareerFact, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_dates(self) -> "Education":
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("Education end date cannot be before start date.")
        return self


class LanguageSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    language: NonEmptyText
    proficiency: NonEmptyText | None = None
    source: FactSource


class ContactValue(BaseModel):
    """One directly extracted contact value with its source evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: NonEmptyText
    source: FactSource


class ContactInfo(BaseModel):
    """Contact details that are explicitly present in the source CV."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    email: ContactValue | None = None
    phone: ContactValue | None = None
    website: ContactValue | None = None


class Certification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyText
    issuer: NonEmptyText | None = None
    date_awarded: date | None = None
    source: FactSource
    facts: tuple[CareerFact, ...] = Field(default_factory=tuple)


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyText
    role: NonEmptyText | None = None
    facts: tuple[CareerFact, ...] = Field(default_factory=tuple)


class Publication(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: NonEmptyText
    publisher: NonEmptyText | None = None
    publication_date: date | None = None
    source: FactSource


class CareerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    full_name: NonEmptyText | None = None
    headline: NonEmptyText | None = None
    contact: ContactInfo | None = None
    summary_facts: tuple[CareerFact, ...] = Field(default_factory=tuple)
    work_experiences: tuple[WorkExperience, ...] = Field(default_factory=tuple)
    education: tuple[Education, ...] = Field(default_factory=tuple)
    skills: tuple[CareerFact, ...] = Field(default_factory=tuple)
    certifications: tuple[Certification, ...] = Field(default_factory=tuple)
    languages: tuple[LanguageSkill, ...] = Field(default_factory=tuple)
    projects: tuple[Project, ...] = Field(default_factory=tuple)
    publications: tuple[Publication, ...] = Field(default_factory=tuple)
    additional_facts: tuple[CareerFact, ...] = Field(default_factory=tuple)

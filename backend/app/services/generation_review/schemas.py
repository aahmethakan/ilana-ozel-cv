from pydantic import BaseModel, ConfigDict, Field

from app.services.generation_strategy import GenerationMode


class DraftReviewClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str
    source: str


class DraftReviewWorkEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    company: str
    title: str
    dates: str | None = None
    claims: tuple[DraftReviewClaim, ...] = Field(default_factory=tuple)


class DraftReviewEducationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    institution: str
    qualification: str | None = None
    dates: str | None = None


class GeneratedCvDraftReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: GenerationMode
    skills: tuple[DraftReviewClaim, ...] = Field(default_factory=tuple)
    work_entries: tuple[DraftReviewWorkEntry, ...] = Field(default_factory=tuple)
    education: tuple[DraftReviewEducationEntry, ...] = Field(default_factory=tuple)

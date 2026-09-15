from pydantic import BaseModel, ConfigDict, Field

from app.domain.job.requirements import JobRequirement


class JobProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str | None = None
    company: str | None = None
    responsibilities: tuple[JobRequirement, ...] = Field(default_factory=tuple)
    requirements: tuple[JobRequirement, ...] = Field(default_factory=tuple)

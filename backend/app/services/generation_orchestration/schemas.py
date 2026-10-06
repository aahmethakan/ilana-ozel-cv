from pydantic import BaseModel, ConfigDict, Field

from app.services.claim_rendering import RenderedClaim
from app.services.generation_strategy import GenerationMode, GenerationPlan
from app.services.section_composition import ComposedEducationEntry, ComposedWorkEntry


class GeneratedCvDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: GenerationMode
    plan: GenerationPlan
    skill_claims: tuple[RenderedClaim, ...] = Field(default_factory=tuple)
    work_fact_claims: tuple[RenderedClaim, ...] = Field(default_factory=tuple)
    work_entries: tuple[ComposedWorkEntry, ...] = Field(default_factory=tuple)
    education_entries: tuple[ComposedEducationEntry, ...] = Field(default_factory=tuple)

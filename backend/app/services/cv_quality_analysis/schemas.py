from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CVQualityDimension(StrEnum):
    COMPLETENESS = "completeness"
    EVIDENCE = "evidence"
    STRUCTURE = "structure"
    ATS_READINESS = "ats_readiness"


class FindingSeverity(StrEnum):
    INFO = "info"
    IMPROVEMENT = "improvement"
    IMPORTANT = "important"


class CVQualityContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cv_language: str | None = None
    locale: str | None = None


class CVQualityFinding(BaseModel):
    """A neutral, traceable explanation of a deterministic quality signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    dimension: CVQualityDimension
    severity: FindingSeverity
    message: str
    score_impact: int
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    remediation_hint: str | None = None


class CVQualityDimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: CVQualityDimension
    score: int = Field(ge=0, le=100)
    max_score: int = Field(ge=1, le=100)
    is_evaluated: bool = True
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class CVQualityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    overall_score: int = Field(ge=0, le=100)
    dimensions: tuple[CVQualityDimensionScore, ...]
    findings: tuple[CVQualityFinding, ...] = Field(default_factory=tuple)
    strengths: tuple[CVQualityFinding, ...] = Field(default_factory=tuple)
    improvement_opportunities: tuple[CVQualityFinding, ...] = Field(default_factory=tuple)

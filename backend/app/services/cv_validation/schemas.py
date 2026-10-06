from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ValidationSeverity(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCK = "BLOCK"


class ValidationOverallStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    validator: str
    code: str
    severity: ValidationSeverity
    message: str
    section: str
    item_reference: str | None = None


class ValidatorResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    validator: str
    status: ValidationSeverity


class CvValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    overall_status: ValidationOverallStatus
    validators: tuple[ValidatorResult, ...]
    issues: tuple[ValidationIssue, ...] = Field(default_factory=tuple)
    pass_count: int
    warning_count: int
    block_count: int

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.domain.career.work_fact_association import WorkFactAssociation, WorkFactAssociationCandidate

class WorkFactAssociationAction(StrEnum): ACCEPT="accept"; REJECT="reject"; LEAVE_UNRESOLVED="leave_unresolved"; CORRECT_TARGET="correct_target"
class WorkFactAssociationResolutionStatus(StrEnum): RESOLVED="resolved"; REJECTED="rejected"; UNRESOLVED="unresolved"
class WorkFactAssociationTarget(BaseModel):
    model_config=ConfigDict(extra="forbid", frozen=True)
    work_record_id: str = Field(min_length=1)
    work_candidate_id: str = Field(min_length=1)

    @field_validator("work_record_id", "work_candidate_id")
    @classmethod
    def validate_canonical_identifier(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("Work association target identifiers must be canonical.")
        return value
class WorkFactAssociationResolutionAudit(BaseModel):
    model_config=ConfigDict(extra="forbid", frozen=True)
    candidate_id:str; action:WorkFactAssociationAction; original_work_record_id:str; original_work_candidate_id:str; corrected_work_record_id:str|None=None; corrected_work_candidate_id:str|None=None; resulting_association_id:str|None=None
class WorkFactAssociationResolutionResult(BaseModel):
    model_config=ConfigDict(extra="forbid", frozen=True)
    candidate:WorkFactAssociationCandidate; status:WorkFactAssociationResolutionStatus; audit:WorkFactAssociationResolutionAudit; association:WorkFactAssociation|None=None

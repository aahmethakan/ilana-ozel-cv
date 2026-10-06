"""Deterministic change and decision projection for an immutable generated draft."""

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.services.generation_orchestration import GeneratedCvDraft
from app.services.generation_review import GeneratedCvDraftReview, build_generated_cv_review


class DraftItemSection(StrEnum):
    SKILL = "skill"
    WORK_ENTRY = "work_entry"
    WORK_FACT = "work_fact"
    EDUCATION = "education"


class DraftDecision(StrEnum):
    KEEP = "keep"
    REMOVE = "remove"


class DraftReason(StrEnum):
    GENERAL_RELEVANT_EVIDENCE = "general_relevant_evidence"
    JOB_REQUIREMENT_MATCH = "job_requirement_match"
    ROLE_ASSOCIATED_EVIDENCE = "role_associated_evidence"
    VERIFIED_EDUCATION = "verified_education"


class DraftChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    change_id: str
    item_id: str
    section: DraftItemSection
    change_type: str = "selected"
    original_text: str | None = None
    proposed_text: str
    reason: DraftReason


class DraftReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item_id: str
    section: DraftItemSection
    text: str
    reason: DraftReason
    decision: DraftDecision = DraftDecision.KEEP


class ReviewedCvDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    draft_id: str
    review: GeneratedCvDraftReview
    items: tuple[DraftReviewItem, ...] = Field(default_factory=tuple)
    changes: tuple[DraftChange, ...] = Field(default_factory=tuple)


def draft_id(draft: GeneratedCvDraft) -> str:
    payload = json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"draft:{hashlib.sha256(payload.encode()).hexdigest()}"


def _reason(draft: GeneratedCvDraft, item_id: str, section: DraftItemSection) -> DraftReason:
    if section is DraftItemSection.EDUCATION:
        return DraftReason.VERIFIED_EDUCATION
    if draft.mode.value == "targeted":
        return DraftReason.JOB_REQUIREMENT_MATCH
    if section in {DraftItemSection.WORK_ENTRY, DraftItemSection.WORK_FACT}:
        return DraftReason.ROLE_ASSOCIATED_EVIDENCE
    return DraftReason.GENERAL_RELEVANT_EVIDENCE


def _items(draft: GeneratedCvDraft) -> tuple[DraftReviewItem, ...]:
    values: list[tuple[str, DraftItemSection, str]] = []
    values.extend((claim.rendered_claim_id, DraftItemSection.SKILL, claim.text) for claim in draft.skill_claims)
    for entry in draft.work_entries:
        values.append((entry.entry_id, DraftItemSection.WORK_ENTRY, entry.identity_claim.text))
        values.extend((claim.rendered_claim_id, DraftItemSection.WORK_FACT, claim.text) for claim in entry.fact_claims)
    values.extend((entry.entry_id, DraftItemSection.EDUCATION, entry.identity_claim.text) for entry in draft.education_entries)
    return tuple(DraftReviewItem(item_id=item_id, section=section, text=text, reason=_reason(draft, item_id, section)) for item_id, section, text in values)


def reviewed_draft(draft: GeneratedCvDraft, decisions: dict[str, DraftDecision] | None = None, rewrites: dict[str, str] | None = None) -> ReviewedCvDraft:
    decisions = decisions or {}
    rewrites = rewrites or {}
    items = tuple(item.model_copy(update={"decision": decisions.get(item.item_id, DraftDecision.KEEP), "text": rewrites.get(item.item_id, item.text)}) for item in _items(draft))
    removed = {item.item_id for item in items if item.decision is DraftDecision.REMOVE}
    work_entries = tuple(
        entry.model_copy(update={"fact_claims": tuple(claim for claim in entry.fact_claims if claim.rendered_claim_id not in removed)})
        for entry in draft.work_entries if entry.entry_id not in removed
    )
    filtered = draft.model_copy(update={
        "skill_claims": tuple(claim.model_copy(update={"text": rewrites.get(claim.rendered_claim_id, claim.text)}) for claim in draft.skill_claims if claim.rendered_claim_id not in removed),
        "work_entries": work_entries,
        "education_entries": tuple(entry for entry in draft.education_entries if entry.entry_id not in removed),
    })
    changes = tuple(DraftChange(change_id=f"change:{item.item_id}", item_id=item.item_id, section=item.section, change_type="rewritten" if item.item_id in rewrites and rewrites[item.item_id] != _items(draft)[list(item.item_id for item in _items(draft)).index(item.item_id)].text else "selected", original_text=next((base.text for base in _items(draft) if base.item_id == item.item_id), None), proposed_text=item.text, reason=item.reason) for item in items)
    return ReviewedCvDraft(draft_id=draft_id(draft), review=build_generated_cv_review(filtered), items=items, changes=changes)

"""Deterministic targeted cover-letter claims built only from rendered CV evidence."""

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.services.generation_orchestration import GeneratedCvDraft
from app.services.cover_letter.rewrite.schemas import CoverLetterRewriteResult
from app.services.controlled_rewrite import RewriteFinalStatus


class CoverLetterDecision(StrEnum):
    KEEP = "keep"
    REMOVE = "remove"


class CoverLetterClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item_id: str
    category: str
    text: str


class CoverLetterDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    draft_id: str
    mode: str = "targeted"
    target_role: str | None = None
    target_company: str | None = None
    opening: str
    claims: tuple[CoverLetterClaim, ...] = Field(default_factory=tuple)
    closing: str = "Thank you for considering my application."


class ReviewedCoverLetterItem(CoverLetterClaim):
    decision: CoverLetterDecision = CoverLetterDecision.KEEP
    rewrite: CoverLetterRewriteResult | None = None


class ReviewedCoverLetter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    draft_id: str
    mode: str = "targeted"
    target_role: str | None = None
    target_company: str | None = None
    opening: str
    body_sections: tuple[str, ...] = Field(default_factory=tuple)
    closing: str
    items: tuple[ReviewedCoverLetterItem, ...] = Field(default_factory=tuple)


def _identity(*, role: str | None, company: str | None, claims: tuple[tuple[str, str], ...]) -> str:
    payload = json.dumps({"role": role, "company": company, "claims": claims}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"cover-letter:{hashlib.sha256(payload.encode()).hexdigest()}"


def generate_cover_letter(*, target_role: str | None, target_company: str | None, targeted_draft: GeneratedCvDraft) -> CoverLetterDraft:
    """Render only already validated targeted selections; never use job words as facts."""
    raw: list[tuple[str, str]] = []
    raw.extend(("SKILL", claim.text) for claim in targeted_draft.skill_claims)
    raw.extend(("EXPERIENCE", claim.text) for entry in targeted_draft.work_entries for claim in entry.fact_claims)
    selected = tuple(dict.fromkeys(raw))
    draft_id = _identity(role=target_role, company=target_company, claims=selected)
    claims = tuple(CoverLetterClaim(item_id=f"cover-item:{index}:{hashlib.sha256(text.encode()).hexdigest()[:16]}", category=category, text=text) for index, (category, text) in enumerate(selected))
    target = f" at {target_company}" if target_company else ""
    opening = f"I am applying for the {target_role} position{target}." if target_role else "I am applying for this position."
    return CoverLetterDraft(draft_id=draft_id, target_role=target_role, target_company=target_company, opening=opening, claims=claims)


def review_cover_letter(draft: CoverLetterDraft, decisions: dict[str, CoverLetterDecision] | None = None, rewrites: dict[str, CoverLetterRewriteResult] | None = None) -> ReviewedCoverLetter:
    decisions = decisions or {}
    rewrites = rewrites or {}
    items = tuple(ReviewedCoverLetterItem(**claim.model_dump(), decision=decisions.get(claim.item_id, CoverLetterDecision.KEEP), rewrite=rewrites.get(claim.item_id)) for claim in draft.claims)
    body = tuple(f"Relevant {item.category.lower()} evidence: {item.rewrite.rewritten_text if item.rewrite and item.rewrite.final_status is RewriteFinalStatus.ACCEPTED else item.text}." for item in items if item.decision is CoverLetterDecision.KEEP)
    return ReviewedCoverLetter(draft_id=draft.draft_id, target_role=draft.target_role, target_company=draft.target_company, opening=draft.opening, body_sections=body, closing=draft.closing, items=items)

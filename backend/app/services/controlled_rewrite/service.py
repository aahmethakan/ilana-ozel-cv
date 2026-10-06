import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from enum import StrEnum


class RewriteProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rewritten_text: str = Field(min_length=1, max_length=600)


class RewriteProvider(Protocol):
    def rewrite_claim(self, *, source_text: str, mode: str) -> RewriteProposal: ...


class ControlledRewriteError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")
_UPPER = re.compile(r"\b[A-Z][A-Za-z0-9+.#-]{1,}\b")
_RISKY = re.compile(r"\b(led|lead|managed|team|expert|advanced|senior|architected|owned)\b", re.I)
_WORDS = re.compile(r"[A-Za-z0-9/+\#-]+")
_ALLOWED_STYLE_WORDS = {"performed", "of", "the", "and", "production", "machinery", "daily", "operations", "based"}


class FactSafetyStatus(StrEnum): SAFE = "safe"; UNSAFE = "unsafe"
class RewriteQualityStatus(StrEnum): IMPROVED = "improved"; UNCHANGED = "unchanged"; NOT_IMPROVED = "not_improved"
class RewriteFinalStatus(StrEnum): ACCEPTED = "accepted"; REJECTED = "rejected"


class RewriteOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    original_text: str
    rewritten_text: str
    fact_safety_status: FactSafetyStatus
    quality_status: RewriteQualityStatus
    final_status: RewriteFinalStatus


def validate_rewrite(*, original: str, rewritten: str) -> None:
    """A small fail-closed factual-anchor gate after the LLM boundary."""
    if rewritten.strip() == original.strip():
        return
    if set(_NUMBER.findall(original)) != set(_NUMBER.findall(rewritten)):
        raise ControlledRewriteError("rewrite_numbers_changed", "Rewrite changed a quantified factual anchor.")
    original_proper = {token.casefold() for token in _UPPER.findall(original)}
    rewritten_proper = {token.casefold() for token in _UPPER.findall(rewritten)}
    if not rewritten_proper <= original_proper | {"performed"}:
        raise ControlledRewriteError("rewrite_named_entity_added", "Rewrite added an unsupported named entity or technology.")
    if _RISKY.search(rewritten) and not _RISKY.search(original):
        raise ControlledRewriteError("rewrite_seniority_added", "Rewrite added unsupported scope or seniority.")
    original_words = {word.casefold() for word in _WORDS.findall(original)}
    added = {word.casefold() for word in _WORDS.findall(rewritten)} - original_words - _ALLOWED_STYLE_WORDS
    if added:
        raise ControlledRewriteError("rewrite_unsupported_content", "Rewrite added unsupported factual content.")


def assess_quality(*, original: str, rewritten: str) -> RewriteQualityStatus:
    if rewritten.strip() == original.strip(): return RewriteQualityStatus.UNCHANGED
    if len(rewritten) > max(len(original) * 2, len(original) + 40): return RewriteQualityStatus.NOT_IMPROVED
    if rewritten.count(".") > 1 or re.search(r"\b(I|my|we|our)\b", rewritten, re.I): return RewriteQualityStatus.NOT_IMPROVED
    if re.search(r"\b(very|highly|various|dynamic|results-driven)\b", rewritten, re.I): return RewriteQualityStatus.NOT_IMPROVED
    return RewriteQualityStatus.IMPROVED


def controlled_rewrite(provider: RewriteProvider, *, original: str, mode: str) -> RewriteOutcome:
    proposal = provider.rewrite_claim(source_text=original, mode=mode)
    try:
        validate_rewrite(original=original, rewritten=proposal.rewritten_text)
    except ControlledRewriteError:
        raise
    quality = assess_quality(original=original, rewritten=proposal.rewritten_text)
    if quality is RewriteQualityStatus.NOT_IMPROVED:
        raise ControlledRewriteError("rewrite_quality_low", "Rewrite did not improve the claim safely.")
    return RewriteOutcome(original_text=original, rewritten_text=proposal.rewritten_text, fact_safety_status=FactSafetyStatus.SAFE, quality_status=quality, final_status=RewriteFinalStatus.ACCEPTED)

"""Small, deterministic equivalence registry for conservative job matching."""

import re
import unicodedata


_PUNCTUATION = re.compile(r"[\-_/.,;:()]+")
_WHITESPACE = re.compile(r"\s+")

# Each group is deliberately narrow.  Do not add product families, role ladders,
# or inferred proficiency to this registry.
_SYNONYM_GROUPS = (
    ("s&op", "sales and operations planning"),
    ("ms excel", "microsoft excel"),
    ("erp system", "erp"),
    ("cv", "curriculum vitae"),
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip().casefold()
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", normalized)).strip()


def _registry() -> dict[str, str]:
    registry: dict[str, str] = {}
    for group in _SYNONYM_GROUPS:
        canonical = normalize_text(group[0])
        for value in group:
            key = normalize_text(value)
            if key in registry and registry[key] != canonical:
                raise ValueError("Controlled synonym registry contains a duplicate mapping.")
            registry[key] = canonical
    return registry


CONTROLLED_SYNONYMS = _registry()


def controlled_canonical(value: str) -> str:
    normalized = normalize_text(value)
    return CONTROLLED_SYNONYMS.get(normalized, normalized)


def is_controlled_synonym(left: str, right: str) -> bool:
    left_normalized, right_normalized = normalize_text(left), normalize_text(right)
    return left_normalized != right_normalized and controlled_canonical(left) == controlled_canonical(right)


def is_conservative_partial(candidate: str, requirement: str) -> bool:
    """Only identify a literal, unqualified candidate phrase within a longer requirement."""
    candidate_tokens = set(normalize_text(candidate).split())
    requirement_tokens = set(normalize_text(requirement).split())
    return bool(candidate_tokens) and candidate_tokens < requirement_tokens

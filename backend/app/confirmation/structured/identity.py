import hashlib
import json


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def structured_record_id(record_type: str, origin_payload: dict[str, object]) -> str:
    """Stable identity based only on record kind and its immutable origin grouping."""

    return _digest({"record_type": record_type, "origin": origin_payload})


def structured_candidate_id(record_id: str, candidate_payload: dict[str, object]) -> str:
    """Stable identity for one exact proposal version of an existing source record."""

    return _digest({"record_id": record_id, "candidate": candidate_payload})

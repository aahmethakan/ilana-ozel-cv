import re

from pydantic import BaseModel, ConfigDict, Field


class PartialDate(BaseModel):
    """A CV date with no invented day component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    year: int = Field(ge=1900, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)


class ParsedDateRange(BaseModel):
    """A deterministic date range retaining its source granularity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: PartialDate
    end: PartialDate | None = None
    is_current: bool = False


_MONTHS = {
    "jan": 1, "january": 1, "ocak": 1,
    "feb": 2, "february": 2, "şubat": 2, "subat": 2,
    "mar": 3, "march": 3, "mart": 3,
    "apr": 4, "april": 4, "nisan": 4,
    "may": 5, "mayıs": 5, "mayis": 5,
    "jun": 6, "june": 6, "haziran": 6,
    "jul": 7, "july": 7, "temmuz": 7,
    "aug": 8, "august": 8, "ağustos": 8, "agustos": 8,
    "sep": 9, "sept": 9, "september": 9, "eylül": 9, "eylul": 9,
    "oct": 10, "october": 10, "ekim": 10,
    "nov": 11, "november": 11, "kasım": 11, "kasim": 11,
    "dec": 12, "december": 12, "aralık": 12, "aralik": 12,
}
_RANGE_PATTERN = re.compile(r"^\s*(?P<start>.+?)\s*(?:-|–|—)\s*(?P<end>present|current|devam ediyor|halen|.+?)\s*$", re.I)
_YEAR_PATTERN = re.compile(r"^(?P<year>\d{4})$")
_NUMERIC_MONTH_PATTERN = re.compile(r"^(?P<month>0[1-9]|1[0-2])[/.](?P<year>\d{4})$")
_NAMED_MONTH_PATTERN = re.compile(r"^(?P<month>[\wçğıöşü]+)\.?\s+(?P<year>\d{4})$", re.I)
_CURRENT_VALUES = {"present", "current", "devam ediyor", "halen"}


def _parse_partial_date(value: str) -> PartialDate | None:
    text = " ".join(value.strip().casefold().split())
    year_match = _YEAR_PATTERN.fullmatch(text)
    if year_match:
        return PartialDate(year=int(year_match["year"]))
    numeric_match = _NUMERIC_MONTH_PATTERN.fullmatch(text)
    if numeric_match:
        return PartialDate(year=int(numeric_match["year"]), month=int(numeric_match["month"]))
    named_match = _NAMED_MONTH_PATTERN.fullmatch(text)
    if named_match and named_match["month"] in _MONTHS:
        return PartialDate(year=int(named_match["year"]), month=_MONTHS[named_match["month"]])
    return None


def parse_date_range(value: str) -> ParsedDateRange | None:
    """Parse only explicit common CV date ranges without inventing days."""

    match = _RANGE_PATTERN.fullmatch(value)
    if match is None:
        return None
    start = _parse_partial_date(match["start"])
    if start is None:
        return None
    end_text = " ".join(match["end"].strip().casefold().split())
    if end_text in _CURRENT_VALUES:
        return ParsedDateRange(start=start, is_current=True)
    end = _parse_partial_date(match["end"])
    if end is None:
        return None
    if (end.year, end.month or 0) < (start.year, start.month or 0):
        return None
    return ParsedDateRange(start=start, end=end)

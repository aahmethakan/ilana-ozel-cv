import re

from pydantic import BaseModel, ConfigDict, Field


class PartialDate(BaseModel):
    """A CV date with no invented day component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    year: int = Field(ge=1900, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)


class ParsedDateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: PartialDate
    end: PartialDate | None = None
    is_current: bool = False
    is_open_ended: bool = False


_MONTHS = {
    "jan": 1, "january": 1, "ocak": 1, "feb": 2, "february": 2, "şubat": 2, "subat": 2,
    "mar": 3, "march": 3, "mart": 3, "apr": 4, "april": 4, "nisan": 4,
    "may": 5, "mayıs": 5, "mayis": 5, "jun": 6, "june": 6, "haziran": 6,
    "jul": 7, "july": 7, "temmuz": 7, "aug": 8, "august": 8, "ağustos": 8, "agustos": 8,
    "sep": 9, "sept": 9, "september": 9, "eylül": 9, "eylul": 9,
    "oct": 10, "october": 10, "ekim": 10, "nov": 11, "november": 11, "kasım": 11, "kasim": 11,
    "dec": 12, "december": 12, "aralık": 12, "aralik": 12,
}
_RANGE_PATTERN = re.compile(r"^\s*(?P<start>.+?)\s*[-–—]\s*(?P<end>.*?)\s*$", re.I)
_YEAR_PATTERN = re.compile(r"^(?P<year>\d{4})$")
_NUMERIC_MONTH_PATTERN = re.compile(r"^(?P<month>0[1-9]|1[0-2])[/.](?P<year>\d{4})$")
_NAMED_MONTH_PATTERN = re.compile(r"^(?P<month>[\wçğıöşü]+)\.?\s+(?P<year>\d{4})$", re.I)
_CURRENT_VALUES = {"present", "current", "devam ediyor", "halen"}


def _parse_partial_date(value: str) -> PartialDate | None:
    text = " ".join(value.strip().casefold().split())
    if match := _YEAR_PATTERN.fullmatch(text):
        return PartialDate(year=int(match["year"]))
    if match := _NUMERIC_MONTH_PATTERN.fullmatch(text):
        return PartialDate(year=int(match["year"]), month=int(match["month"]))
    if match := _NAMED_MONTH_PATTERN.fullmatch(text):
        month = _MONTHS.get(match["month"])
        if month is not None:
            return PartialDate(year=int(match["year"]), month=month)
    return None


def parse_date_range(value: str) -> ParsedDateRange | None:
    """Parse explicit CV date ranges while preserving partial and open-ended dates."""

    match = _RANGE_PATTERN.fullmatch(value)
    if match is None:
        return None
    start = _parse_partial_date(match["start"])
    if start is None:
        return None
    end_value = match["end"].strip()
    if not end_value:
        return ParsedDateRange(start=start, is_open_ended=True)
    if " ".join(end_value.casefold().split()) in _CURRENT_VALUES:
        return ParsedDateRange(start=start, is_current=True)
    end = _parse_partial_date(end_value)
    if end is None or (end.year, end.month or 0) < (start.year, start.month or 0):
        return None
    return ParsedDateRange(start=start, end=end)

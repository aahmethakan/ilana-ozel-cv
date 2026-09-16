from pydantic import BaseModel, ConfigDict, Field


class CareerDate(BaseModel):
    """A career date that preserves whether a month was actually known."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    year: int = Field(ge=1900, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)

    def definitely_before(self, other: "CareerDate") -> bool:
        """Return true only when this date's latest possible month precedes the other's earliest."""

        return (self.year, self.month or 12) < (other.year, other.month or 1)

    def definitely_after(self, other: "CareerDate") -> bool:
        """Return true only when this date's earliest possible month follows the other's latest."""

        return (self.year, self.month or 1) > (other.year, other.month or 12)

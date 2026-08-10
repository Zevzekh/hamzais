"""Normalised source-data record (specification section 7).

Raw source column names never leave the QVD service - everything downstream
speaks :class:`QVDRecord`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.utils.normalize import make_lookup_key

LookupKey = tuple[str | None, str | None, str | None]


@dataclass(frozen=True)
class QVDRecord:
    """One normalised row of operational source data."""

    pn: str | None
    sn: str | None
    eo: str | None
    hours: float | int | None = None
    cycles: float | int | None = None
    days: float | int | None = None
    reference_date: datetime | None = None
    modified_date: datetime | None = None
    source: str = ""
    row_number: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> LookupKey:
        """Normalised ``(pn, sn, eo)`` matching key."""

        return make_lookup_key(self.pn, self.sn, self.eo)

    def describe(self) -> str:
        return f"{self.pn or '?'} / {self.sn or '?'} / {self.eo or '?'}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "pn": self.pn,
            "sn": self.sn,
            "eo": self.eo,
            "hours": self.hours,
            "cycles": self.cycles,
            "days": self.days,
            "reference_date": self.reference_date,
            "modified_date": self.modified_date,
            "source": self.source,
            **dict(self.extra),
        }

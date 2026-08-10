"""Read-only view models built at runtime (specification sections 33 and 46).

Actual utilisation comes from the latest source data and is joined in memory.
It is deliberately never written back into the active extension database just
so it can be displayed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.enums import ComparisonStatus, LimitStatus
from app.models.extension_item import ExtensionItem


def _exceeds(actual: float | int | None, limit: float | int | None) -> bool | None:
    if actual is None or limit is None:
        return None
    return actual >= limit


@dataclass(frozen=True)
class AppliedExtensionView:
    """An active extension joined with the latest operational source data."""

    item: ExtensionItem
    actual_hours: float | int | None = None
    actual_cycles: float | int | None = None
    actual_days: float | int | None = None
    qvd_modified_date: datetime | None = None
    status: ComparisonStatus = ComparisonStatus.CURRENT
    limit_status: LimitStatus = LimitStatus.UNKNOWN
    detail: str | None = None

    # --- convenience accessors used by the UI ---------------------------
    @property
    def extension_id(self) -> str:
        return self.item.extension_id

    @property
    def application_id(self) -> str:
        return self.item.application_id

    @property
    def application_date(self) -> datetime | None:
        return self.item.created_at

    @property
    def warning(self) -> bool:
        """True when the record needs a human look (sections 31, 32, 36)."""

        return self.status is not ComparisonStatus.CURRENT

    @property
    def status_text(self) -> str:
        """Status with an icon so colour is never the only signal."""

        return f"{self.status.icon} {self.status.label}"

    def to_row(self) -> dict[str, Any]:
        """Flat dictionary for tabular display and filtering."""

        item = self.item
        return {
            "status": self.status.value,
            "status_text": self.status_text,
            "application_id": item.application_id,
            "extension_id": item.extension_id,
            "extension_type": item.extension_type.value,
            "pn": item.pn,
            "sn": item.sn,
            "eo": item.eo,
            "current_hours": item.current_hours,
            "current_cycles": item.current_cycles,
            "current_days": item.current_days,
            "current_date": item.current_date,
            "extended_hours": item.extended_hours,
            "extended_cycles": item.extended_cycles,
            "extended_days": item.extended_days,
            "extended_date": item.extended_date,
            "actual_hours": self.actual_hours,
            "actual_cycles": self.actual_cycles,
            "actual_days": self.actual_days,
            "application_date": item.created_at,
            "qvd_modified_date": self.qvd_modified_date,
            "created_by": item.created_by,
            "limit_status": self.limit_status.value,
            "warning_status": self.warning,
        }


@dataclass(frozen=True)
class CompletionPreview:
    """Everything the completion confirmation screen shows (section 46)."""

    item: ExtensionItem
    actual_hours: float | int | None
    actual_cycles: float | int | None
    actual_days: float | int | None
    qvd_modified_date: datetime | None
    completion_date: datetime
    source_status: ComparisonStatus

    @property
    def source_found(self) -> bool:
        return self.source_status is not ComparisonStatus.NOT_FOUND

    @property
    def exceeds_extended_hours(self) -> bool | None:
        return _exceeds(self.actual_hours, self.item.extended_hours)

    @property
    def exceeds_extended_cycles(self) -> bool | None:
        return _exceeds(self.actual_cycles, self.item.extended_cycles)

    @property
    def exceeds_extended_days(self) -> bool | None:
        return _exceeds(self.actual_days, self.item.extended_days)

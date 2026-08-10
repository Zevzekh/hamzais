"""Table building, filtering and sorting for the list screens.

Filtering happens on the in-memory joined view, so nothing here reads a file
(specification sections 33, 66 and 67).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import pandas as pd

from app.models.enums import ComparisonStatus, ExtensionType
from app.models.views import AppliedExtensionView
from app.ui.components.formatting import format_date, format_datetime, format_number

#: Column layout of the Applied Extensions table (specification section 34).
APPLIED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("status_text", "Status"),
    ("extension_id", "Extension ID"),
    ("pn", "PN"),
    ("sn", "SN"),
    ("eo", "EO"),
    ("current_hours", "Current Hours"),
    ("current_cycles", "Current Cycles"),
    ("current_days", "Current Days"),
    ("extended_hours", "Extended Hours"),
    ("extended_cycles", "Extended Cycles"),
    ("extended_days", "Extended Days"),
    ("actual_hours", "Actual Hours"),
    ("actual_cycles", "Actual Cycles"),
    ("actual_days", "Actual Days"),
    ("application_date", "Application Date"),
    ("qvd_modified_date", "Source Modified Date"),
)

NUMBER_FIELDS = frozenset(
    {
        "current_hours",
        "current_cycles",
        "current_days",
        "extended_hours",
        "extended_cycles",
        "extended_days",
        "actual_hours",
        "actual_cycles",
        "actual_days",
    }
)
DATE_FIELDS = frozenset({"current_date", "extended_date"})
DATETIME_FIELDS = frozenset({"application_date", "qvd_modified_date"})

#: Sortable columns offered to the user (specification section 67).
SORT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("application_date", "Application Date"),
    ("qvd_modified_date", "Source Modified Date"),
    ("pn", "PN"),
    ("sn", "SN"),
    ("eo", "EO"),
    ("actual_hours", "Actual Hours"),
    ("actual_cycles", "Actual Cycles"),
    ("actual_days", "Actual Days"),
    ("status", "Status"),
)


@dataclass(frozen=True)
class AppliedFilters:
    """Filter selection for the list screens (specification section 66)."""

    search: str = ""
    pn: str = ""
    sn: str = ""
    eo: str = ""
    application_id: str = ""
    extension_type: ExtensionType | None = None
    statuses: tuple[ComparisonStatus, ...] = ()

    def is_active(self) -> bool:
        return bool(
            self.search
            or self.pn
            or self.sn
            or self.eo
            or self.application_id
            or self.extension_type
            or self.statuses
        )


def _contains(haystack: Any, needle: str) -> bool:
    return needle.strip().upper() in str(haystack or "").upper()


def filter_views(
    views: Sequence[AppliedExtensionView], filters: AppliedFilters
) -> list[AppliedExtensionView]:
    """Apply the filter selection to the joined view."""

    result = list(views)
    if filters.extension_type is not None:
        result = [v for v in result if v.item.extension_type is filters.extension_type]
    if filters.statuses:
        wanted = set(filters.statuses)
        result = [v for v in result if v.status in wanted]
    for value, attribute in (
        (filters.pn, "pn"),
        (filters.sn, "sn"),
        (filters.eo, "eo"),
    ):
        if value.strip():
            result = [v for v in result if _contains(getattr(v.item, attribute), value)]
    if filters.application_id.strip():
        result = [
            v for v in result if _contains(v.item.application_id, filters.application_id)
        ]
    if filters.search.strip():
        needle = filters.search
        result = [
            v
            for v in result
            if any(
                _contains(field, needle)
                for field in (
                    v.item.pn,
                    v.item.sn,
                    v.item.eo,
                    v.item.application_id,
                    v.item.extension_id,
                    v.item.created_by,
                )
            )
        ]
    return result


def sort_views(
    views: Sequence[AppliedExtensionView], sort_by: str, descending: bool = False
) -> list[AppliedExtensionView]:
    """Sort while keeping missing values together at the end."""

    def key(view: AppliedExtensionView):
        value = view.to_row().get(sort_by)
        if value is None:
            return (1, "")
        if isinstance(value, (int, float)):
            return (0, float(value))
        if hasattr(value, "timestamp"):
            return (0, value.timestamp())
        return (0, str(value).upper())

    missing_last = sorted(views, key=key, reverse=descending)
    return list(missing_last)


def views_to_frame(
    views: Iterable[AppliedExtensionView],
    columns: Sequence[tuple[str, str]] = APPLIED_COLUMNS,
) -> pd.DataFrame:
    """Build the display frame with every value already formatted."""

    records = []
    for view in views:
        row = view.to_row()
        formatted = {}
        for field_name, header in columns:
            value = row.get(field_name)
            if field_name in NUMBER_FIELDS:
                formatted[header] = format_number(value)
            elif field_name in DATE_FIELDS:
                formatted[header] = format_date(value)
            elif field_name in DATETIME_FIELDS:
                formatted[header] = format_datetime(value)
            else:
                formatted[header] = "" if value is None else str(value)
        records.append(formatted)
    headers = [header for _, header in columns]
    return pd.DataFrame(records, columns=headers)


def views_to_export_rows(views: Iterable[AppliedExtensionView]) -> list[dict[str, Any]]:
    """Raw (unformatted) rows for a download."""

    return [view.to_row() for view in views]


def status_counts(views: Sequence[AppliedExtensionView]) -> dict[ComparisonStatus, int]:
    counts = {status: 0 for status in ComparisonStatus}
    for view in views:
        counts[view.status] += 1
    return counts

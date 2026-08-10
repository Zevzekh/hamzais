"""Presentation helpers.

Formatting lives here and only here: stored values stay as real numbers and
real datetimes (specification sections 56 and 57).
"""

from __future__ import annotations

from typing import Any

from app.models.enums import ComparisonStatus
from app.utils.dates import format_date as _format_date
from app.utils.dates import format_datetime as _format_datetime

EMPTY = "—"


def format_number(value: Any, empty: str = EMPTY) -> str:
    """Thousands separated, with decimals only when the value has them."""

    if value is None or value == "":
        return empty
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"


def format_date(value: Any, fmt: str = "%d-%b-%Y", empty: str = EMPTY) -> str:
    return _format_date(value, fmt, empty)


def format_datetime(value: Any, fmt: str = "%d-%b-%Y %H:%M", empty: str = EMPTY) -> str:
    return _format_datetime(value, fmt, empty)


def format_text(value: Any, empty: str = EMPTY) -> str:
    text = "" if value is None else str(value).strip()
    return text or empty


def status_badge(status: ComparisonStatus) -> str:
    """Icon plus words - never colour alone (specification section 35)."""

    return f"{status.icon} {status.label}"


def status_message(status: ComparisonStatus, detail: str | None = None) -> str:
    if status is ComparisonStatus.SOURCE_CHANGED:
        return detail or "Source data changed after application."
    if status is ComparisonStatus.NOT_FOUND:
        return detail or "No matching record in the latest operational data."
    return detail or "Matches the latest operational data."


def utilisation_line(
    hours: Any, cycles: Any, days: Any, empty: str = EMPTY
) -> str:
    return (
        f"Hours: {format_number(hours, empty)} · "
        f"Cycles: {format_number(cycles, empty)} · "
        f"Days: {format_number(days, empty)}"
    )

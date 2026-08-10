"""Deterministic mock source data for the automated tests.

Specification section 73: tests never depend on production source files.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ENGINEERING_ORDER_HEADERS = [
    "PART_NUMBER",
    "SERIAL_NUMBER",
    "ENGINEERING_ORDER",
    "CURRENT_HOURS",
    "CURRENT_CYCLES",
    "CURRENT_DAYS",
    "CURRENT_DATE",
    "MODIFIED_DATE",
]

HARD_TIME_LIMIT_HEADERS = [
    "PART_NUMBER",
    "SERIAL_NUMBER",
    "TASK_REFERENCE",
    "CURRENT_HOURS",
    "CURRENT_CYCLES",
    "CURRENT_DAYS",
    "CURRENT_DATE",
    "MODIFIED_DATE",
]

ACTUAL_HEADERS = [
    "PART_NUMBER",
    "SERIAL_NUMBER",
    "ENGINEERING_ORDER",
    "ACTUAL_HOURS",
    "ACTUAL_CYCLES",
    "ACTUAL_DAYS",
    "ACTUAL_DATE",
    "MODIFIED_DATE",
]

#: The fixture data from specification section 73.
ENGINEERING_ORDER_ROWS: tuple[dict[str, Any], ...] = (
    {
        "pn": "PN001",
        "sn": "SN001",
        "eo": "EO001",
        "hours": 12000,
        "cycles": 8000,
        "days": 1500,
        "reference_date": date(2026, 8, 1),
        "modified_date": date(2026, 8, 1),
    },
    {
        "pn": "PN002",
        "sn": "SN002",
        "eo": "EO002",
        "hours": 15000,
        "cycles": 9500,
        "days": 1800,
        "reference_date": date(2026, 8, 8),
        "modified_date": date(2026, 8, 8),
    },
    {
        "pn": "PN003",
        "sn": "SN003",
        "eo": "EO003",
        "hours": 9000.5,
        "cycles": 6100,
        "days": 1100,
        "reference_date": date(2026, 7, 20),
        "modified_date": date(2026, 7, 20),
    },
)

HARD_TIME_LIMIT_ROWS: tuple[dict[str, Any], ...] = (
    {
        "pn": "PN010",
        "sn": "SN010",
        "eo": "HTL-500",
        "hours": 4000,
        "cycles": 2500,
        "days": 700,
        "reference_date": date(2026, 8, 3),
        "modified_date": date(2026, 8, 3),
    },
)

ACTUAL_ROWS: tuple[dict[str, Any], ...] = (
    {
        "pn": "PN001",
        "sn": "SN001",
        "eo": "EO001",
        "hours": 12800,
        "cycles": 8390,
        "days": 1570,
        "reference_date": date(2026, 8, 10),
        "modified_date": date(2026, 8, 1),
    },
    {
        "pn": "PN002",
        "sn": "SN002",
        "eo": "EO002",
        "hours": 15600,
        "cycles": 9800,
        "days": 1850,
        "reference_date": date(2026, 8, 10),
        "modified_date": date(2026, 8, 8),
    },
    {
        "pn": "PN010",
        "sn": "SN010",
        "eo": "HTL-500",
        "hours": 4200,
        "cycles": 2600,
        "days": 730,
        "reference_date": date(2026, 8, 10),
        "modified_date": date(2026, 8, 5),
    },
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def write_source_csv(
    path: Path,
    headers: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
    *,
    field_order: Sequence[str] = (
        "pn",
        "sn",
        "eo",
        "hours",
        "cycles",
        "days",
        "reference_date",
        "modified_date",
    ),
) -> Path:
    """Write rows in the raw column layout the source systems use."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_text(row.get(field)) for field in field_order])
    return path


def write_engineering_order(path: Path, rows: Iterable[Mapping[str, Any]] | None = None) -> Path:
    return write_source_csv(
        path, ENGINEERING_ORDER_HEADERS, ENGINEERING_ORDER_ROWS if rows is None else rows
    )


def write_hard_time_limit(path: Path, rows: Iterable[Mapping[str, Any]] | None = None) -> Path:
    return write_source_csv(
        path, HARD_TIME_LIMIT_HEADERS, HARD_TIME_LIMIT_ROWS if rows is None else rows
    )


def write_actual_utilization(path: Path, rows: Iterable[Mapping[str, Any]] | None = None) -> Path:
    return write_source_csv(path, ACTUAL_HEADERS, ACTUAL_ROWS if rows is None else rows)


def row(
    pn: str,
    sn: str,
    eo: str,
    *,
    hours: Any = None,
    cycles: Any = None,
    days: Any = None,
    reference_date: Any = None,
    modified_date: Any = None,
) -> dict[str, Any]:
    """Build a single source row for a bespoke test scenario."""

    return {
        "pn": pn,
        "sn": sn,
        "eo": eo,
        "hours": hours,
        "cycles": cycles,
        "days": days,
        "reference_date": reference_date,
        "modified_date": modified_date,
    }

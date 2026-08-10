"""Immutable identifier generation (specification sections 4, 16 and 48).

``application_id``
    ``EXT-2026-000001`` - one per user submission.
``extension_id``
    ``EXT-2026-000001-001`` - one per extension row, immutable for life.

Row positions in a dataframe are never used as identity.
"""

from __future__ import annotations

import re
from typing import Iterable

APPLICATION_ID_RE = re.compile(r"^(?P<prefix>[A-Z]+)-(?P<year>\d{4})-(?P<sequence>\d{6})$")
EXTENSION_ID_RE = re.compile(
    r"^(?P<application_id>[A-Z]+-\d{4}-\d{6})-(?P<row>\d{3,})$"
)

SEQUENCE_WIDTH = 6
ROW_WIDTH = 3


def parse_application_id(application_id: str) -> tuple[str, int, int] | None:
    """Return ``(prefix, year, sequence)`` or ``None`` when unparsable."""

    match = APPLICATION_ID_RE.match(str(application_id).strip().upper())
    if not match:
        return None
    return match["prefix"], int(match["year"]), int(match["sequence"])


def next_application_id(
    year: int,
    existing_ids: Iterable[str],
    *,
    prefix: str = "EXT",
) -> str:
    """Generate the next free application id for ``year``.

    ``existing_ids`` must cover every dataset (active, completed and deleted)
    so an identifier is never reused after an extension has been archived.
    """

    prefix = prefix.upper()
    highest = 0
    for candidate in existing_ids:
        if not candidate:
            continue
        parsed = parse_application_id(str(candidate))
        if not parsed:
            continue
        candidate_prefix, candidate_year, sequence = parsed
        if candidate_prefix == prefix and candidate_year == year:
            highest = max(highest, sequence)
    return f"{prefix}-{year:04d}-{highest + 1:0{SEQUENCE_WIDTH}d}"


def build_extension_id(application_id: str, row_number: int) -> str:
    """Build the row identifier. ``row_number`` is 1 based."""

    if row_number < 1:
        raise ValueError("row_number is 1 based")
    return f"{application_id}-{row_number:0{ROW_WIDTH}d}"


def build_extension_ids(application_id: str, count: int) -> list[str]:
    return [build_extension_id(application_id, index) for index in range(1, count + 1)]


def application_id_of(extension_id: str) -> str | None:
    """Recover the owning application id from an extension id."""

    match = EXTENSION_ID_RE.match(str(extension_id).strip().upper())
    return match["application_id"] if match else None


def new_document_id(application_id: str, sequence: int) -> str:
    """Stable identifier for a stored proof document."""

    return f"{application_id}-DOC-{sequence:03d}"

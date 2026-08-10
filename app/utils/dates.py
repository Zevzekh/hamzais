"""Date and time helpers.

The application stores timezone aware UTC datetimes everywhere (section 56).
Formatting to something like ``10-Aug-2026`` only ever happens in the UI or in
the export mapper.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from app.utils.normalize import is_null_like

UTC = timezone.utc

#: Formats tried, in order, when a source system hands us a date as text.
DEFAULT_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y",
    "%d.%m.%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%Y%m%d",
)


def now_utc() -> datetime:
    """Current timezone aware UTC timestamp."""

    return datetime.now(tz=UTC)


def ensure_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime, convert an aware one to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_utc_datetime(
    value: Any,
    formats: Iterable[str] | None = None,
    *,
    null_tokens: Iterable[str] | None = None,
) -> datetime | None:
    """Coerce ``value`` into a timezone aware UTC datetime.

    Accepts ``datetime``, ``date``, ISO-ish strings and objects exposing
    ``to_pydatetime`` (pandas timestamps).  Returns ``None`` for missing
    values and raises :class:`ValueError` when text cannot be understood.
    """

    if is_null_like(value, null_tokens):
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if callable(to_pydatetime):
        return ensure_utc(to_pydatetime())

    text = str(value).strip()
    candidates = tuple(formats) if formats else ()
    for fmt in (*candidates, *DEFAULT_DATE_FORMATS):
        try:
            return ensure_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue
    try:
        return ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"{value!r} is not a recognisable date") from exc


def parse_optional_datetime(value: Any, formats: Iterable[str] | None = None) -> datetime | None:
    """Like :func:`to_utc_datetime` but returns ``None`` instead of raising."""

    try:
        return to_utc_datetime(value, formats)
    except ValueError:
        return None


def start_of_day(value: datetime) -> datetime:
    value = ensure_utc(value)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def format_date(value: Any, fmt: str = "%d-%b-%Y", empty: str = "") -> str:
    """Format a stored datetime for display. Presentation layer only."""

    parsed = parse_optional_datetime(value)
    return parsed.strftime(fmt) if parsed else empty


def format_datetime(value: Any, fmt: str = "%d-%b-%Y %H:%M", empty: str = "") -> str:
    return format_date(value, fmt, empty)


def timestamp_slug(value: datetime | None = None) -> str:
    """Compact timestamp used in generated file names."""

    return ensure_utc(value or now_utc()).strftime("%Y%m%d_%H%M%S")


def is_after(left: datetime | None, right: datetime | None) -> bool:
    """``left > right`` on real datetimes, tolerating missing values.

    Comparing formatted strings would silently produce wrong answers, so both
    sides are coerced first (section 31).
    """

    left_dt = parse_optional_datetime(left)
    right_dt = parse_optional_datetime(right)
    if left_dt is None or right_dt is None:
        return False
    return left_dt > right_dt

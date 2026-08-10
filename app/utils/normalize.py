"""Value normalisation shared by the source-data and matching layers.

Sections 30 and 58 of the specification: ``"ABC123"`` and ``" ABC123 "`` must
never be treated as different parts, and the many ways a source system spells
"no value" must all collapse to a single representation.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

#: Text values that mean "no value" in the source systems.
DEFAULT_NULL_TOKENS: frozenset[str] = frozenset(
    {"", "-", "--", "n/a", "na", "n.a.", "none", "null", "nan", "?", "#n/a"}
)

_WHITESPACE = re.compile(r"\s+")
_THOUSANDS = re.compile(r"(?<=\d)[ ,'](?=\d{3}\b)")


def is_null_like(value: Any, null_tokens: Iterable[str] | None = None) -> bool:
    """Return ``True`` when ``value`` represents a missing value."""

    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        tokens = frozenset(t.lower() for t in null_tokens) if null_tokens else DEFAULT_NULL_TOKENS
        return value.strip().lower() in tokens
    # pandas / numpy missing markers without importing pandas here
    if value.__class__.__name__ in {"NaTType", "NAType"}:
        return True
    return False


def normalize_text(value: Any, null_tokens: Iterable[str] | None = None) -> str | None:
    """Trim and collapse internal whitespace, returning ``None`` when empty."""

    if is_null_like(value, null_tokens):
        return None
    text = _WHITESPACE.sub(" ", str(value).strip())
    return text or None


def normalize_key(value: Any, null_tokens: Iterable[str] | None = None) -> str | None:
    """Normalise a matching key (PN / SN / EO): trimmed, collapsed, upper case."""

    text = normalize_text(value, null_tokens)
    return text.upper() if text is not None else None


def make_lookup_key(pn: Any, sn: Any, eo: Any) -> tuple[str | None, str | None, str | None]:
    """Build the normalised ``(pn, sn, eo)`` matching key (section 64)."""

    return (normalize_key(pn), normalize_key(sn), normalize_key(eo))


def normalize_number(
    value: Any,
    *,
    null_tokens: Iterable[str] | None = None,
    prefer_int: bool = True,
) -> int | float | None:
    """Parse a numeric source value.

    Values are not blindly cast to ``int`` (section 57): a whole number is
    returned as ``int``, anything fractional keeps its ``float``
    representation.  ``None`` is returned for missing values and is never
    confused with ``0`` (section 15).
    """

    if is_null_like(value, null_tokens):
        return None
    if isinstance(value, bool):
        raise ValueError(f"Boolean is not a valid numeric value: {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        text = _THOUSANDS.sub("", text)
        text = text.replace(" ", "")
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError(f"{value!r} is not a valid number") from exc
    if math.isnan(number) or math.isinf(number):
        return None
    if prefer_int and number.is_integer():
        return int(number)
    return number


def normalize_optional_number(value: Any, **kwargs: Any) -> int | float | None:
    """Like :func:`normalize_number` but returns ``None`` for unparsable text."""

    try:
        return normalize_number(value, **kwargs)
    except ValueError:
        return None

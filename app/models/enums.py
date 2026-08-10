"""Enumerations used across the application.

Business states are never represented by free text strings (specification
section 5 / 49).
"""

from __future__ import annotations

from enum import Enum


class _LabelledEnum(str, Enum):
    """String enum with a human readable label and a forgiving parser."""

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def parse(cls, value, default=None):
        if value is None:
            return default
        if isinstance(value, cls):
            return value
        text = str(value).strip().upper().replace(" ", "_").replace("-", "_")
        for member in cls:
            if member.value == text or member.name == text:
                return member
        return default


class ExtensionType(_LabelledEnum):
    """The kind of extension being applied for."""

    ENGINEERING_ORDER = "ENGINEERING_ORDER"
    HARD_TIME_LIMIT = "HARD_TIME_LIMIT"

    @property
    def label(self) -> str:
        return {
            ExtensionType.ENGINEERING_ORDER: "Engineering Order",
            ExtensionType.HARD_TIME_LIMIT: "Hard Time Limits",
        }[self]


class ExtensionStatus(_LabelledEnum):
    """Lifecycle state of a stored extension row (specification section 49)."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DELETED = "DELETED"


class ComparisonStatus(_LabelledEnum):
    """Result of comparing an active extension with the latest source data."""

    CURRENT = "CURRENT"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    NOT_FOUND = "NOT_FOUND"

    @property
    def label(self) -> str:
        return {
            ComparisonStatus.CURRENT: "Current",
            ComparisonStatus.SOURCE_CHANGED: "Source data changed",
            ComparisonStatus.NOT_FOUND: "Not found in source data",
        }[self]

    @property
    def icon(self) -> str:
        """Icon shown next to the status.

        Colour alone is never used to convey the state (section 35).
        """

        return {
            ComparisonStatus.CURRENT: "✓",
            ComparisonStatus.SOURCE_CHANGED: "⚠",
            ComparisonStatus.NOT_FOUND: "✖",
        }[self]


class LimitStatus(_LabelledEnum):
    """Optional utilisation monitoring (specification section 37).

    The states exist so that the calculation can be switched on later without
    reshaping the view model.  Nothing in the application completes an
    extension automatically.
    """

    UNKNOWN = "UNKNOWN"
    WITHIN_LIMIT = "WITHIN_LIMIT"
    APPROACHING_LIMIT = "APPROACHING_LIMIT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"

    @property
    def label(self) -> str:
        return {
            LimitStatus.UNKNOWN: "Unknown",
            LimitStatus.WITHIN_LIMIT: "Within limit",
            LimitStatus.APPROACHING_LIMIT: "Approaching limit",
            LimitStatus.LIMIT_EXCEEDED: "Limit exceeded",
        }[self]


class DuplicatePolicy(_LabelledEnum):
    """What to do when an active extension already covers a PN/SN/EO."""

    BLOCK = "BLOCK"
    WARN = "WARN"
    ALLOW = "ALLOW"


class Severity(_LabelledEnum):
    """Severity of a validation issue."""

    ERROR = "ERROR"
    WARNING = "WARNING"

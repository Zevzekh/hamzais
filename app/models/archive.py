"""Archive records (specification sections 41, 44 and 45).

Archived rows preserve every original application value exactly and add the
provenance of the event that archived them.  Nothing is ever deleted
permanently (section 85.10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.models.enums import ExtensionStatus
from app.models.extension_item import ITEM_FIELDS, ExtensionItem
from app.utils.dates import to_utc_datetime
from app.utils.normalize import normalize_number

COMPLETION_FIELDS: tuple[str, ...] = (
    "actual_hours_at_completion",
    "actual_cycles_at_completion",
    "actual_days_at_completion",
    "qvd_modified_date_at_completion",
    "completion_date",
    "completed_by",
    "completion_source_status",
)

DELETION_FIELDS: tuple[str, ...] = (
    "deleted_at",
    "deleted_by",
    "deletion_reason",
)

COMPLETED_FIELDS: tuple[str, ...] = ITEM_FIELDS + COMPLETION_FIELDS
DELETED_FIELDS: tuple[str, ...] = ITEM_FIELDS + DELETION_FIELDS


@dataclass(frozen=True)
class CompletedExtension:
    """An extension moved into the completed archive."""

    item: ExtensionItem
    completion_date: datetime
    completed_by: str
    actual_hours_at_completion: float | int | None = None
    actual_cycles_at_completion: float | int | None = None
    actual_days_at_completion: float | int | None = None
    qvd_modified_date_at_completion: datetime | None = None
    completion_source_status: str | None = None

    @property
    def extension_id(self) -> str:
        return self.item.extension_id

    def to_row(self) -> dict[str, Any]:
        row = self.item.with_status(ExtensionStatus.COMPLETED).to_row()
        row.update(
            {
                "actual_hours_at_completion": self.actual_hours_at_completion,
                "actual_cycles_at_completion": self.actual_cycles_at_completion,
                "actual_days_at_completion": self.actual_days_at_completion,
                "qvd_modified_date_at_completion": self.qvd_modified_date_at_completion,
                "completion_date": self.completion_date,
                "completed_by": self.completed_by,
                "completion_source_status": self.completion_source_status,
            }
        )
        return {name: row[name] for name in COMPLETED_FIELDS}

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CompletedExtension":
        return cls(
            item=ExtensionItem.from_row(row),
            completion_date=to_utc_datetime(row.get("completion_date")),
            completed_by=str(row.get("completed_by") or ""),
            actual_hours_at_completion=normalize_number(row.get("actual_hours_at_completion")),
            actual_cycles_at_completion=normalize_number(row.get("actual_cycles_at_completion")),
            actual_days_at_completion=normalize_number(row.get("actual_days_at_completion")),
            qvd_modified_date_at_completion=to_utc_datetime(
                row.get("qvd_modified_date_at_completion")
            ),
            completion_source_status=row.get("completion_source_status"),
        )


@dataclass(frozen=True)
class DeletedExtension:
    """An extension moved into the deleted archive."""

    item: ExtensionItem
    deleted_at: datetime
    deleted_by: str
    deletion_reason: str | None = None

    @property
    def extension_id(self) -> str:
        return self.item.extension_id

    def to_row(self) -> dict[str, Any]:
        row = self.item.with_status(ExtensionStatus.DELETED).to_row()
        row.update(
            {
                "deleted_at": self.deleted_at,
                "deleted_by": self.deleted_by,
                "deletion_reason": self.deletion_reason,
            }
        )
        return {name: row[name] for name in DELETED_FIELDS}

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "DeletedExtension":
        return cls(
            item=ExtensionItem.from_row(row),
            deleted_at=to_utc_datetime(row.get("deleted_at")),
            deleted_by=str(row.get("deleted_by") or ""),
            deletion_reason=row.get("deletion_reason"),
        )

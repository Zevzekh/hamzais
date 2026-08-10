"""The stored extension row (specification section 16).

An :class:`ExtensionItem` is a historical record.  Once created, the *current*
values are frozen forever - they are never refreshed from newer source data
(sections 20 and 85.9).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.models.enums import ExtensionStatus, ExtensionType
from app.utils.dates import to_utc_datetime
from app.utils.normalize import make_lookup_key, normalize_key, normalize_number

#: Column order used by the active Parquet dataset (specification section 22).
ITEM_FIELDS: tuple[str, ...] = (
    "application_id",
    "extension_id",
    "extension_type",
    "pn",
    "sn",
    "eo",
    "current_hours",
    "current_cycles",
    "current_days",
    "current_date",
    "extended_hours",
    "extended_cycles",
    "extended_days",
    "extended_date",
    "qvd_modified_date_at_application",
    "created_at",
    "created_by",
    "proof_document_reference",
    "status",
)


@dataclass(frozen=True)
class ExtensionItem:
    """One extension row, identified for life by ``extension_id``."""

    extension_id: str
    application_id: str
    extension_type: ExtensionType
    pn: str
    sn: str
    eo: str

    current_hours: float | int | None = None
    current_cycles: float | int | None = None
    current_days: float | int | None = None
    current_date: datetime | None = None

    extended_hours: float | int | None = None
    extended_cycles: float | int | None = None
    extended_days: float | int | None = None
    extended_date: datetime | None = None

    qvd_modified_date_at_application: datetime | None = None
    created_at: datetime | None = None
    created_by: str = ""
    proof_document_reference: str | None = None
    status: ExtensionStatus = ExtensionStatus.ACTIVE

    # --- derived ---------------------------------------------------------
    @property
    def key(self) -> tuple[str | None, str | None, str | None]:
        return make_lookup_key(self.pn, self.sn, self.eo)

    @property
    def document_paths(self) -> list[str]:
        """Relative document paths held in ``proof_document_reference``."""

        return decode_document_reference(self.proof_document_reference)

    def describe(self) -> str:
        return f"{self.pn} / {self.sn} / {self.eo}"

    def with_status(self, status: ExtensionStatus) -> "ExtensionItem":
        return replace(self, status=status)

    # --- storage mapping --------------------------------------------------
    def to_row(self) -> dict[str, Any]:
        """Flat dictionary matching the stored column order."""

        row = asdict(self)
        row["extension_type"] = self.extension_type.value
        row["status"] = self.status.value
        return {name: row[name] for name in ITEM_FIELDS}

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ExtensionItem":
        """Rebuild an item from a stored row."""

        return cls(
            extension_id=str(row["extension_id"]),
            application_id=str(row["application_id"]),
            extension_type=ExtensionType.parse(
                row.get("extension_type"), ExtensionType.ENGINEERING_ORDER
            ),
            pn=normalize_key(row.get("pn")) or "",
            sn=normalize_key(row.get("sn")) or "",
            eo=normalize_key(row.get("eo")) or "",
            current_hours=normalize_number(row.get("current_hours")),
            current_cycles=normalize_number(row.get("current_cycles")),
            current_days=normalize_number(row.get("current_days")),
            current_date=to_utc_datetime(row.get("current_date")),
            extended_hours=normalize_number(row.get("extended_hours")),
            extended_cycles=normalize_number(row.get("extended_cycles")),
            extended_days=normalize_number(row.get("extended_days")),
            extended_date=to_utc_datetime(row.get("extended_date")),
            qvd_modified_date_at_application=to_utc_datetime(
                row.get("qvd_modified_date_at_application")
            ),
            created_at=to_utc_datetime(row.get("created_at")),
            created_by=str(row.get("created_by") or ""),
            proof_document_reference=row.get("proof_document_reference"),
            status=ExtensionStatus.parse(row.get("status"), ExtensionStatus.ACTIVE),
        )


def encode_document_reference(paths: Sequence[str]) -> str | None:
    """Serialise proof document paths for the ``proof_document_reference`` column.

    Full document metadata lives in its own dataset; this column keeps a
    readable list of relative paths so a single row stays self describing
    (specification section 22).
    """

    cleaned = [str(path) for path in paths if path]
    return json.dumps(cleaned) if cleaned else None


def decode_document_reference(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    text = str(value).strip()
    if not text:
        return []
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return [part.strip() for part in text.split(";") if part.strip()]
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    return [str(decoded)]

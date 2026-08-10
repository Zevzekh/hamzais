"""Extension application and proof document models (specification section 4).

One user submission (an :class:`ExtensionApplication`) carries one or many
:class:`~app.models.extension_item.ExtensionItem` rows that all share the same
``application_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.models.enums import ExtensionType
from app.models.extension_item import ExtensionItem
from app.utils.dates import to_utc_datetime

#: Column order of the proof document metadata dataset (section 59).
DOCUMENT_FIELDS: tuple[str, ...] = (
    "document_id",
    "application_id",
    "original_filename",
    "stored_filename",
    "relative_path",
    "size_bytes",
    "content_type",
    "uploaded_at",
    "uploaded_by",
)


@dataclass(frozen=True)
class ProofDocument:
    """A stored supporting document.

    The file itself lives on disk; only metadata is kept in the database
    (specification section 9 - never put binaries in Parquet).
    """

    document_id: str
    application_id: str
    original_filename: str
    stored_filename: str
    relative_path: str
    size_bytes: int = 0
    content_type: str | None = None
    uploaded_at: datetime | None = None
    uploaded_by: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "application_id": self.application_id,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "uploaded_at": self.uploaded_at,
            "uploaded_by": self.uploaded_by,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ProofDocument":
        size = row.get("size_bytes")
        return cls(
            document_id=str(row["document_id"]),
            application_id=str(row["application_id"]),
            original_filename=str(row.get("original_filename") or ""),
            stored_filename=str(row.get("stored_filename") or ""),
            relative_path=str(row.get("relative_path") or ""),
            size_bytes=int(size) if size is not None else 0,
            content_type=row.get("content_type"),
            uploaded_at=to_utc_datetime(row.get("uploaded_at")),
            uploaded_by=str(row.get("uploaded_by") or ""),
        )


@dataclass(frozen=True)
class ExtensionApplication:
    """One submission: shared header plus the extension rows it produced."""

    application_id: str
    extension_type: ExtensionType
    created_at: datetime
    created_by: str
    proof_documents: Sequence[ProofDocument] = field(default_factory=tuple)
    extension_items: Sequence[ExtensionItem] = field(default_factory=tuple)

    @property
    def row_count(self) -> int:
        return len(self.extension_items)

    @property
    def document_count(self) -> int:
        return len(self.proof_documents)

    @classmethod
    def from_items(
        cls,
        items: Sequence[ExtensionItem],
        documents: Sequence[ProofDocument] = (),
    ) -> "ExtensionApplication":
        """Rebuild the header from stored rows (used by 'View application')."""

        if not items:
            raise ValueError("an application needs at least one extension item")
        first = items[0]
        created_at = min(
            (item.created_at for item in items if item.created_at is not None),
            default=None,
        )
        return cls(
            application_id=first.application_id,
            extension_type=first.extension_type,
            created_at=created_at,
            created_by=first.created_by,
            proof_documents=tuple(documents),
            extension_items=tuple(items),
        )

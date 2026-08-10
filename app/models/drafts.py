"""Mutable models used while a user is filling in the Create screen.

The UI must not keep important business state only in widget variables
(specification section 60): it edits these drafts, and the service layer turns
a validated draft into immutable stored records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.models.enums import ExtensionType
from app.models.qvd_record import QVDRecord
from app.utils.normalize import make_lookup_key, normalize_key


@dataclass
class PendingDocument:
    """A file the user attached but which has not been stored yet."""

    filename: str
    data: bytes
    content_type: str | None = None

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @classmethod
    def from_upload(cls, uploaded: Any) -> "PendingDocument":
        """Adapt an upload object (e.g. a Streamlit ``UploadedFile``).

        Keeps the UI framework out of the service layer.
        """

        name = getattr(uploaded, "name", None) or "document"
        if hasattr(uploaded, "getvalue"):
            data = uploaded.getvalue()
        elif hasattr(uploaded, "read"):
            data = uploaded.read()
        else:  # pragma: no cover - defensive
            raise TypeError(f"cannot read uploaded file of type {type(uploaded)!r}")
        return cls(
            filename=name,
            data=bytes(data),
            content_type=getattr(uploaded, "type", None),
        )


@dataclass
class ExtensionRowDraft:
    """One in-progress extension row."""

    #: Stable handle so a UI can keep widget state attached to the right row
    #: when rows above it are removed. Never persisted.
    uid: str = field(default_factory=lambda: uuid4().hex)

    pn: str = ""
    sn: str = ""
    eo: str = ""

    # Populated from the source data only - never typed by the user.
    current_hours: float | int | None = None
    current_cycles: float | int | None = None
    current_days: float | int | None = None
    current_date: datetime | None = None
    qvd_modified_date: datetime | None = None
    lookup_done: bool = False
    lookup_error: str | None = None
    #: The PN/SN/EO the current values were retrieved for, so an edited
    #: identifier can invalidate stale current values.
    source_key: tuple[str | None, str | None, str | None] | None = None

    extended_hours: float | int | None = None
    extended_cycles: float | int | None = None
    extended_days: float | int | None = None
    extended_date: datetime | None = None

    @property
    def key(self) -> tuple[str | None, str | None, str | None]:
        return make_lookup_key(self.pn, self.sn, self.eo)

    @property
    def identifiers_complete(self) -> bool:
        """True once PN, SN and EO all carry a value (section 13)."""

        return all(part is not None for part in self.key)

    def apply_source_record(self, record: QVDRecord) -> None:
        """Freeze the current values retrieved from the source data."""

        self.current_hours = record.hours
        self.current_cycles = record.cycles
        self.current_days = record.days
        self.current_date = record.reference_date
        self.qvd_modified_date = record.modified_date
        self.lookup_done = True
        self.lookup_error = None
        self.source_key = self.key

    @property
    def current_values_stale(self) -> bool:
        """True when PN/SN/EO changed after the current values were loaded."""

        return self.lookup_done and self.source_key != self.key

    def clear_source_record(self, error: str | None = None) -> None:
        self.current_hours = None
        self.current_cycles = None
        self.current_days = None
        self.current_date = None
        self.qvd_modified_date = None
        self.lookup_done = False
        self.lookup_error = error
        self.source_key = None

    def normalized(self) -> "ExtensionRowDraft":
        self.pn = normalize_key(self.pn) or ""
        self.sn = normalize_key(self.sn) or ""
        self.eo = normalize_key(self.eo) or ""
        return self


@dataclass
class ExtensionApplicationDraft:
    """The whole in-progress submission."""

    extension_type: ExtensionType | None = None
    rows: list[ExtensionRowDraft] = field(default_factory=list)
    documents: list[PendingDocument] = field(default_factory=list)
    created_by: str = ""

    def add_row(self) -> ExtensionRowDraft:
        row = ExtensionRowDraft()
        self.rows.append(row)
        return row

    def remove_row(self, index: int) -> None:
        if 0 <= index < len(self.rows):
            self.rows.pop(index)

    def add_document(self, document: PendingDocument) -> None:
        self.documents.append(document)

    def remove_document(self, index: int) -> None:
        if 0 <= index < len(self.documents):
            self.documents.pop(index)

    def has_document(self, filename: str, size_bytes: int) -> bool:
        return any(
            doc.filename == filename and doc.size_bytes == size_bytes
            for doc in self.documents
        )

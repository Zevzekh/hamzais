"""Repository abstraction over a single Parquet dataset.

The rest of the application only ever talks to repositories, never to Parquet
(specification sections 62 and 82).  Swapping Parquet for Oracle later means
providing another implementation of this interface - no UI, validation,
source-data or export code changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable, Sequence

import pyarrow as pa

from app.services.parquet_service import ParquetService, StagedWrite


class ExtensionRepository(ABC):
    """The storage contract used by the service layer."""

    @abstractmethod
    def read_all(self) -> list[dict[str, Any]]:
        """Every stored row as a plain dictionary."""

    @abstractmethod
    def append(self, records: Sequence[dict[str, Any]]) -> None:
        """Add rows to the dataset."""

    @abstractmethod
    def get_by_id(self, extension_id: str) -> dict[str, Any] | None:
        """One row by its immutable identifier."""

    @abstractmethod
    def remove_by_id(self, extension_id: str) -> dict[str, Any] | None:
        """Remove one row, returning it."""

    @abstractmethod
    def count(self) -> int:
        """Number of stored rows."""


class ParquetExtensionRepository(ExtensionRepository):
    """Parquet backed repository.

    Mutating methods are convenience wrappers around the staging API; the
    service layer uses :meth:`stage_records` directly when a change has to span
    two datasets atomically.
    """

    #: Column holding the immutable record identity.
    id_column = "extension_id"

    def __init__(
        self,
        path: Path,
        schema: pa.Schema,
        parquet_service: ParquetService | None = None,
        name: str = "",
    ) -> None:
        self.path = Path(path)
        self.schema = schema
        self.parquet = parquet_service or ParquetService()
        self.name = name or self.path.stem

    # --- reading ---------------------------------------------------------
    def read_all(self) -> list[dict[str, Any]]:
        return self.parquet.read_records(self.path, self.schema)

    def count(self) -> int:
        return len(self.read_all())

    def get_by_id(self, extension_id: str) -> dict[str, Any] | None:
        return self.find_by_id(self.read_all(), extension_id)

    def exists(self, extension_id: str) -> bool:
        return self.get_by_id(extension_id) is not None

    def get_by_application(self, application_id: str) -> list[dict[str, Any]]:
        target = str(application_id).strip().upper()
        return [
            record
            for record in self.read_all()
            if str(record.get("application_id") or "").strip().upper() == target
        ]

    def application_ids(self) -> set[str]:
        return {
            str(record.get("application_id"))
            for record in self.read_all()
            if record.get("application_id")
        }

    @classmethod
    def find_by_id(
        cls, records: Iterable[dict[str, Any]], extension_id: str
    ) -> dict[str, Any] | None:
        target = str(extension_id).strip().upper()
        for record in records:
            if str(record.get(cls.id_column) or "").strip().upper() == target:
                return record
        return None

    # --- staged writes ---------------------------------------------------
    def stage_records(self, records: Sequence[dict[str, Any]]) -> StagedWrite:
        """Prepare a full replacement of this dataset without committing."""

        return self.parquet.stage(self.path, records, self.schema)

    def stage_append(
        self, new_records: Sequence[dict[str, Any]], existing: Sequence[dict[str, Any]] | None = None
    ) -> StagedWrite:
        current = list(existing if existing is not None else self.read_all())
        current.extend(new_records)
        return self.stage_records(current)

    def stage_without(
        self, extension_id: str, existing: Sequence[dict[str, Any]] | None = None
    ) -> StagedWrite:
        current = list(existing if existing is not None else self.read_all())
        target = str(extension_id).strip().upper()
        remaining = [
            record
            for record in current
            if str(record.get(self.id_column) or "").strip().upper() != target
        ]
        return self.stage_records(remaining)

    # --- convenience mutations -------------------------------------------
    def append(self, records: Sequence[dict[str, Any]]) -> None:
        if not records:
            return
        with self.parquet.transaction():
            self.parquet.commit([self.stage_append(records)])

    def remove_by_id(self, extension_id: str) -> dict[str, Any] | None:
        with self.parquet.transaction():
            existing = self.read_all()
            record = self.find_by_id(existing, extension_id)
            if record is None:
                return None
            self.parquet.commit([self.stage_without(extension_id, existing)])
            return record

    def replace_all(self, records: Sequence[dict[str, Any]]) -> None:
        with self.parquet.transaction():
            self.parquet.commit([self.stage_records(records)])

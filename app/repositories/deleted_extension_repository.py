"""Deleted extension archive (specification sections 40 and 41).

Deleting an extension never discards it - the original record is preserved
exactly and gains deletion provenance.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.config.settings import Settings, get_settings
from app.models.archive import DeletedExtension
from app.repositories.base import ParquetExtensionRepository
from app.repositories.schemas import DELETED_SCHEMA
from app.services.parquet_service import ParquetService


class DeletedExtensionRepository(ParquetExtensionRepository):
    def __init__(
        self,
        settings: Settings | None = None,
        parquet_service: ParquetService | None = None,
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            path=settings.deleted_file,
            schema=DELETED_SCHEMA,
            parquet_service=parquet_service or ParquetService(settings),
            name="deleted",
        )

    def read_records_typed(self) -> list[DeletedExtension]:
        return [DeletedExtension.from_row(row) for row in self.read_all()]

    def get_record(self, extension_id: str) -> DeletedExtension | None:
        row = self.get_by_id(extension_id)
        return DeletedExtension.from_row(row) if row else None

    def append_records(self, records: Sequence[DeletedExtension]) -> None:
        self.append([record.to_row() for record in records])

    def stage_append_records(
        self,
        records: Sequence[DeletedExtension],
        existing: Sequence[dict[str, Any]] | None = None,
    ):
        return self.stage_append([record.to_row() for record in records], existing)

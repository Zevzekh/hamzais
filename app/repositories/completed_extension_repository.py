"""Completed extension archive (specification sections 44 and 45)."""

from __future__ import annotations

from typing import Any, Sequence

from app.config.settings import Settings, get_settings
from app.models.archive import CompletedExtension
from app.repositories.base import ParquetExtensionRepository
from app.repositories.schemas import COMPLETED_SCHEMA
from app.services.parquet_service import ParquetService


class CompletedExtensionRepository(ParquetExtensionRepository):
    """Extensions that ran their course, with the utilisation at completion."""

    def __init__(
        self,
        settings: Settings | None = None,
        parquet_service: ParquetService | None = None,
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            path=settings.completed_file,
            schema=COMPLETED_SCHEMA,
            parquet_service=parquet_service or ParquetService(settings),
            name="completed",
        )

    def read_records_typed(self) -> list[CompletedExtension]:
        return [CompletedExtension.from_row(row) for row in self.read_all()]

    def get_record(self, extension_id: str) -> CompletedExtension | None:
        row = self.get_by_id(extension_id)
        return CompletedExtension.from_row(row) if row else None

    def append_records(self, records: Sequence[CompletedExtension]) -> None:
        self.append([record.to_row() for record in records])

    def stage_append_records(
        self,
        records: Sequence[CompletedExtension],
        existing: Sequence[dict[str, Any]] | None = None,
    ):
        return self.stage_append([record.to_row() for record in records], existing)

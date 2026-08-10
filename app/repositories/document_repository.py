"""Proof document metadata dataset (specification sections 22 and 59).

Keeping document metadata in its own dataset - rather than serialising
everything into the extension row - is the maintainable option called out in
section 22.  Binary content never enters Parquet.
"""

from __future__ import annotations

from typing import Sequence

from app.config.settings import Settings, get_settings
from app.models.extension import ProofDocument
from app.repositories.base import ParquetExtensionRepository
from app.repositories.schemas import DOCUMENT_SCHEMA
from app.services.parquet_service import ParquetService


class DocumentRepository(ParquetExtensionRepository):
    """Metadata for every stored supporting document."""

    id_column = "document_id"

    def __init__(
        self,
        settings: Settings | None = None,
        parquet_service: ParquetService | None = None,
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            path=settings.documents_file,
            schema=DOCUMENT_SCHEMA,
            parquet_service=parquet_service or ParquetService(settings),
            name="documents",
        )

    def read_documents(self) -> list[ProofDocument]:
        return [ProofDocument.from_row(row) for row in self.read_all()]

    def documents_for_application(self, application_id: str) -> list[ProofDocument]:
        return [ProofDocument.from_row(row) for row in self.get_by_application(application_id)]

    def append_documents(self, documents: Sequence[ProofDocument]) -> None:
        self.append([document.to_row() for document in documents])

    def stage_append_documents(self, documents: Sequence[ProofDocument], existing=None):
        return self.stage_append([document.to_row() for document in documents], existing)

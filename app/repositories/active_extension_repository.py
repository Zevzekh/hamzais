"""Active extensions - ``extensions.parquet`` (specification sections 21/22)."""

from __future__ import annotations

from typing import Any, Sequence

from app.config.settings import Settings, get_settings
from app.models.extension_item import ExtensionItem
from app.repositories.base import ParquetExtensionRepository
from app.repositories.schemas import ACTIVE_SCHEMA
from app.services.parquet_service import ParquetService
from app.utils.normalize import make_lookup_key


class ActiveExtensionRepository(ParquetExtensionRepository):
    """Holds only the extensions that are currently in force."""

    def __init__(
        self,
        settings: Settings | None = None,
        parquet_service: ParquetService | None = None,
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            path=settings.active_file,
            schema=ACTIVE_SCHEMA,
            parquet_service=parquet_service or ParquetService(settings),
            name="active",
        )

    # --- domain level helpers -------------------------------------------
    def read_items(self) -> list[ExtensionItem]:
        return [ExtensionItem.from_row(row) for row in self.read_all()]

    def get_item(self, extension_id: str) -> ExtensionItem | None:
        row = self.get_by_id(extension_id)
        return ExtensionItem.from_row(row) if row else None

    def items_for_application(self, application_id: str) -> list[ExtensionItem]:
        return [ExtensionItem.from_row(row) for row in self.get_by_application(application_id)]

    def find_by_key(self, pn: str, sn: str, eo: str) -> list[ExtensionItem]:
        """Active extensions matching a normalised PN/SN/EO (section 18)."""

        wanted = make_lookup_key(pn, sn, eo)
        return [item for item in self.read_items() if item.key == wanted]

    def append_items(self, items: Sequence[ExtensionItem]) -> None:
        self.append([item.to_row() for item in items])

    def stage_append_items(
        self, items: Sequence[ExtensionItem], existing: Sequence[dict[str, Any]] | None = None
    ):
        return self.stage_append([item.to_row() for item in items], existing)

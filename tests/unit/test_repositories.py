"""Storage layer behaviour (specification sections 21-25, 48, 62 and 81)."""

from __future__ import annotations

from datetime import datetime

import pyarrow.parquet as pq
import pytest

from app.errors import StorageError
from app.models.archive import CompletedExtension, DeletedExtension
from app.models.enums import ExtensionStatus, ExtensionType
from app.models.extension_item import ExtensionItem, decode_document_reference
from app.repositories.active_extension_repository import ActiveExtensionRepository
from app.repositories.completed_extension_repository import CompletedExtensionRepository
from app.repositories.deleted_extension_repository import DeletedExtensionRepository
from app.services.parquet_service import ParquetService
from app.utils.dates import UTC, now_utc


def make_item(
    extension_id: str = "EXT-2026-000001-001",
    application_id: str = "EXT-2026-000001",
    pn: str = "PN001",
    sn: str = "SN001",
    eo: str = "EO001",
    **overrides,
) -> ExtensionItem:
    defaults = dict(
        extension_id=extension_id,
        application_id=application_id,
        extension_type=ExtensionType.ENGINEERING_ORDER,
        pn=pn,
        sn=sn,
        eo=eo,
        current_hours=12000,
        current_cycles=8000,
        current_days=1500,
        current_date=datetime(2026, 8, 1, tzinfo=UTC),
        extended_hours=13000,
        extended_cycles=None,
        extended_days=None,
        extended_date=None,
        qvd_modified_date_at_application=datetime(2026, 8, 1, tzinfo=UTC),
        created_at=now_utc(),
        created_by="tester",
        proof_document_reference='["documents/EXT-2026-000001/report.pdf"]',
        status=ExtensionStatus.ACTIVE,
    )
    defaults.update(overrides)
    return ExtensionItem(**defaults)


class TestActiveRepository:
    def test_reading_an_absent_file_gives_an_empty_dataset(self, settings):
        repo = ActiveExtensionRepository(settings)
        assert repo.read_all() == []
        assert repo.count() == 0

    def test_append_and_read_round_trip(self, settings):
        repo = ActiveExtensionRepository(settings)
        item = make_item()
        repo.append_items([item])

        stored = repo.read_items()
        assert len(stored) == 1
        assert stored[0].extension_id == item.extension_id
        assert stored[0].current_hours == 12000
        assert stored[0].extension_type is ExtensionType.ENGINEERING_ORDER
        assert stored[0].created_at is not None

    def test_null_and_zero_survive_a_round_trip(self, settings):
        """Section 15: NULL and 0 are different business states."""

        repo = ActiveExtensionRepository(settings)
        repo.append_items(
            [make_item(extended_cycles=None, extended_days=0, extension_id="EXT-2026-000001-001")]
        )
        stored = repo.read_items()[0]
        assert stored.extended_cycles is None
        assert stored.extended_days == 0

    def test_timestamps_keep_their_timezone(self, settings):
        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])
        assert repo.read_items()[0].created_at.tzinfo is not None

    def test_records_are_found_by_identifier_not_by_position(self, settings):
        """Section 48: a dataframe row number is never identity."""

        repo = ActiveExtensionRepository(settings)
        repo.append_items(
            [
                make_item(extension_id="EXT-2026-000001-001", pn="PN001"),
                make_item(extension_id="EXT-2026-000001-002", pn="PN002"),
                make_item(extension_id="EXT-2026-000001-003", pn="PN003"),
            ]
        )
        repo.remove_by_id("EXT-2026-000001-002")

        remaining = {item.extension_id for item in repo.read_items()}
        assert remaining == {"EXT-2026-000001-001", "EXT-2026-000001-003"}
        assert repo.get_item("EXT-2026-000001-003").pn == "PN003"

    def test_remove_is_case_insensitive_and_reports_nothing_removed(self, settings):
        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])
        assert repo.remove_by_id("ext-2026-000001-001") is not None
        assert repo.remove_by_id("EXT-2026-000009-001") is None

    def test_lookup_by_key_is_normalised(self, settings):
        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])
        assert repo.find_by_key(" pn001 ", "sn001", "eo001")

    def test_rows_of_one_application_share_the_application_id(self, settings):
        repo = ActiveExtensionRepository(settings)
        repo.append_items(
            [
                make_item(extension_id="EXT-2026-000001-001"),
                make_item(extension_id="EXT-2026-000001-002", pn="PN002"),
            ]
        )
        assert len(repo.items_for_application("EXT-2026-000001")) == 2

    def test_document_reference_decodes_to_paths(self, settings):
        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])
        stored = repo.read_items()[0]
        assert stored.document_paths == ["documents/EXT-2026-000001/report.pdf"]


class TestArchiveRepositories:
    def test_completed_archive_keeps_the_completion_snapshot(self, settings):
        repo = CompletedExtensionRepository(settings)
        completed = CompletedExtension(
            item=make_item(),
            completion_date=now_utc(),
            completed_by="closer",
            actual_hours_at_completion=12800,
            actual_cycles_at_completion=8390,
            actual_days_at_completion=1570,
            qvd_modified_date_at_completion=datetime(2026, 8, 9, tzinfo=UTC),
            completion_source_status="CURRENT",
        )
        repo.append_records([completed])

        stored = repo.read_records_typed()[0]
        assert stored.actual_hours_at_completion == 12800
        assert stored.completed_by == "closer"
        assert stored.item.current_hours == 12000  # original values preserved
        assert stored.item.status is ExtensionStatus.COMPLETED

    def test_deleted_archive_keeps_deletion_provenance(self, settings):
        repo = DeletedExtensionRepository(settings)
        repo.append_records(
            [
                DeletedExtension(
                    item=make_item(),
                    deleted_at=now_utc(),
                    deleted_by="remover",
                    deletion_reason="raised in error",
                )
            ]
        )
        stored = repo.read_records_typed()[0]
        assert stored.deleted_by == "remover"
        assert stored.deletion_reason == "raised in error"
        assert stored.item.status is ExtensionStatus.DELETED
        assert stored.item.extended_hours == 13000  # original values preserved


class TestSafeWrites:
    def test_no_temporary_file_is_left_behind(self, settings):
        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])
        assert not list(settings.active_dir.glob("*.tmp.parquet"))

    def test_a_backup_is_taken_before_replacing(self, settings):
        """Section 81: keep a rolling backup of a Parquet business database."""

        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])
        assert not list(settings.backup_dir.glob("extensions_*.parquet"))

        repo.append_items([make_item(extension_id="EXT-2026-000001-002")])
        assert list(settings.backup_dir.glob("extensions_*.parquet"))

    def test_backups_are_pruned_to_the_retention_limit(self, settings):
        repo = ActiveExtensionRepository(settings)
        for index in range(1, 8):
            repo.append_items([make_item(extension_id=f"EXT-2026-000001-{index:03d}")])
        backups = list(settings.backup_dir.glob("extensions_*.parquet"))
        assert len(backups) <= settings.backup_retention

    def test_the_original_survives_a_failed_write(self, settings, monkeypatch):
        """Section 24: never destroy the only copy."""

        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])
        original_bytes = settings.active_file.read_bytes()

        def explode(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(pq, "write_table", explode)
        with pytest.raises(StorageError):
            repo.append_items([make_item(extension_id="EXT-2026-000001-002")])

        assert settings.active_file.read_bytes() == original_bytes
        assert len(ActiveExtensionRepository(settings).read_items()) == 1

    def test_a_staged_write_does_not_touch_the_target(self, settings):
        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])

        staged = repo.stage_append([make_item(extension_id="EXT-2026-000001-002").to_row()])
        assert len(repo.read_items()) == 1  # not committed yet
        assert staged.temp_path.exists()

        repo.parquet.commit([staged])
        assert len(repo.read_items()) == 2

    def test_a_new_column_does_not_make_old_files_unreadable(self, settings):
        repo = ActiveExtensionRepository(settings)
        repo.append_items([make_item()])

        table = pq.read_table(settings.active_file)
        pq.write_table(table.drop(["proof_document_reference"]), settings.active_file)

        items = ActiveExtensionRepository(settings).read_items()
        assert len(items) == 1
        assert items[0].proof_document_reference is None


class TestParquetService:
    def test_transaction_serialises_writers(self, settings):
        service = ParquetService(settings)
        with service.transaction():
            pass  # acquiring and releasing must not raise
        with service.transaction():
            pass

    def test_document_reference_decoding_handles_legacy_text(self):
        assert decode_document_reference("a.pdf; b.pdf") == ["a.pdf", "b.pdf"]
        assert decode_document_reference(None) == []
        assert decode_document_reference('["a.pdf"]') == ["a.pdf"]

"""End to end workflow tests (specification section 72, tests A to F).

Each test drives the service layer exactly as the UI does, against temporary
source files and temporary Parquet databases.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta

import pytest

from app.config.qvd_config import ACTUAL_UTILIZATION
from app.errors import RecordNotFoundError, StorageError, ValidationFailedError
from app.models.enums import ComparisonStatus, ExtensionStatus
from app.repositories.active_extension_repository import ActiveExtensionRepository
from app.repositories.completed_extension_repository import CompletedExtensionRepository
from app.repositories.deleted_extension_repository import DeletedExtensionRepository
from app.utils.dates import now_utc
from tests.fixtures import qvd_data


def future_date(days: int = 1) -> datetime:
    return now_utc() + timedelta(days=days)


def past_date(days: int = 30) -> datetime:
    return now_utc() - timedelta(days=days)


class TestACreate:
    """Test A - create an application with two rows."""

    @pytest.fixture
    def created(self, service, make_draft):
        draft = make_draft(
            service,
            [("PN001", "SN001", "EO001"), ("PN002", "SN002", "EO002")],
            extended_hours=20_000,
            extended_cycles=12_000,
        )
        return service.create_extension(draft, "tester")

    def test_two_rows_are_stored_in_the_active_database(self, service, created, settings):
        assert settings.active_file.exists()
        stored = ActiveExtensionRepository(settings).read_items()
        assert len(stored) == 2
        assert {item.pn for item in stored} == {"PN001", "PN002"}
        assert all(item.status is ExtensionStatus.ACTIVE for item in stored)

    def test_rows_share_an_application_id_and_have_unique_extension_ids(self, created):
        items = created.application.extension_items
        assert {item.application_id for item in items} == {"EXT-2026-000001"}
        assert [item.extension_id for item in items] == [
            "EXT-2026-000001-001",
            "EXT-2026-000001-002",
        ]

    def test_current_values_are_frozen_from_the_source(self, service, created):
        stored = {item.pn: item for item in service.get_active_extensions()}
        assert stored["PN001"].current_hours == 12000
        assert stored["PN001"].current_cycles == 8000
        assert stored["PN001"].current_days == 1500
        assert stored["PN002"].current_hours == 15000

    def test_extended_values_are_stored_as_entered(self, service, created):
        item = service.get_active_extensions()[0]
        assert item.extended_hours == 20_000
        assert item.extended_cycles == 12_000
        assert item.extended_days is None

    def test_the_application_captures_who_and_when(self, created):
        application = created.application
        assert application.created_by == "tester"
        assert application.created_at is not None
        assert all(item.created_by == "tester" for item in application.extension_items)

    def test_the_source_modification_date_is_frozen(self, created):
        item = created.application.extension_items[0]
        assert item.qvd_modified_date_at_application is not None

    def test_proof_documents_are_stored_and_referenced(self, service, created, settings):
        documents = service.get_documents(created.application_id)
        assert len(documents) == 1
        assert (settings.data_dir / documents[0].relative_path).exists()

        item = service.get_active_extensions()[0]
        assert item.document_paths == [documents[0].relative_path]

    def test_an_export_file_is_generated(self, created):
        assert created.export_error is None
        assert created.export_path is not None and created.export_path.exists()

        with created.export_path.open(encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == 3  # header plus two extension rows
        assert rows[1][1] == "EXT-2026-000001-001"

    def test_a_second_application_continues_the_sequence(self, service, created, make_draft):
        second = service.create_extension(
            make_draft(service, [("PN003", "SN003", "EO003")]), "tester"
        )
        assert second.application_id == "EXT-2026-000002"
        assert second.application.extension_items[0].extension_id == "EXT-2026-000002-001"

    def test_an_invalid_draft_is_refused(self, service, make_draft):
        draft = make_draft(service, [("PN999", "SN999", "EO999")])
        with pytest.raises(ValidationFailedError):
            service.create_extension(draft, "tester")
        assert service.get_active_extensions() == []

    def test_important_actions_are_logged(self, service, created, settings):
        log = settings.log_file.read_text(encoding="utf-8")
        assert "event=EXTENSION_CREATED" in log
        assert f"application_id={created.application_id}" in log
        assert "event=DOCUMENT_UPLOADED" in log
        assert "event=EXPORT_CREATED" in log
        assert "event=PARQUET_WRITE" in log


class TestBWarning:
    """Test B - the source record changed after the extension was created."""

    def test_a_later_source_modification_raises_a_warning(
        self, service, make_draft, write_source
    ):
        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]), "tester")

        write_source(
            ACTUAL_UTILIZATION,
            [
                qvd_data.row(
                    "PN001",
                    "SN001",
                    "EO001",
                    hours=13100,
                    cycles=8600,
                    days=1620,
                    modified_date=future_date(),
                )
            ],
        )

        view = service.get_active_extensions_with_actuals(force_refresh=True)[0]
        assert view.status is ComparisonStatus.SOURCE_CHANGED
        assert view.warning is True
        assert "⚠" in view.status_text

    def test_the_latest_actual_values_are_shown(self, service, make_draft, write_source):
        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]), "tester")
        write_source(
            ACTUAL_UTILIZATION,
            [
                qvd_data.row(
                    "PN001",
                    "SN001",
                    "EO001",
                    hours=13100,
                    cycles=8600,
                    days=1620,
                    modified_date=future_date(),
                )
            ],
        )

        view = service.get_active_extensions_with_actuals(force_refresh=True)[0]
        assert view.actual_hours == 13100
        assert view.actual_cycles == 8600
        assert view.actual_days == 1620

    def test_the_warning_never_rewrites_stored_history(
        self, service, make_draft, write_source, settings
    ):
        """Sections 20 and 32: a warning is informational only."""

        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]), "tester")
        before = ActiveExtensionRepository(settings).read_all()

        write_source(
            ACTUAL_UTILIZATION,
            [qvd_data.row("PN001", "SN001", "EO001", hours=99999, modified_date=future_date())],
        )
        view = service.get_active_extensions_with_actuals(force_refresh=True)[0]

        assert view.item.current_hours == 12000  # not the newer 99999
        assert ActiveExtensionRepository(settings).read_all() == before

    def test_a_missing_source_record_is_its_own_state(
        self, service, make_draft, write_source
    ):
        """Section 36: NOT_FOUND is never treated as normal."""

        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]), "tester")
        write_source(ACTUAL_UTILIZATION, [qvd_data.row("PN777", "SN777", "EO777", hours=1)])

        view = service.get_active_extensions_with_actuals(force_refresh=True)[0]
        assert view.status is ComparisonStatus.NOT_FOUND
        assert view.warning is True
        assert view.actual_hours is None

    def test_ambiguous_operational_data_is_surfaced_not_guessed(
        self, service, make_draft, write_source
    ):
        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]), "tester")
        write_source(
            ACTUAL_UTILIZATION,
            [
                qvd_data.row("PN001", "SN001", "EO001", hours=13000),
                qvd_data.row("PN001", "SN001", "EO001", hours=13500),
            ],
        )

        view = service.get_active_extensions_with_actuals(force_refresh=True)[0]
        assert view.status is ComparisonStatus.NOT_FOUND
        assert "2 operational records" in view.detail


class TestCCurrent:
    """Test C - the source has not moved since the extension was created."""

    def test_an_older_source_modification_is_current(self, service, make_draft, write_source):
        write_source(
            ACTUAL_UTILIZATION,
            [
                qvd_data.row(
                    "PN001",
                    "SN001",
                    "EO001",
                    hours=12800,
                    cycles=8390,
                    days=1570,
                    modified_date=past_date(),
                )
            ],
        )
        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]), "tester")

        view = service.get_active_extensions_with_actuals(force_refresh=True)[0]
        assert view.status is ComparisonStatus.CURRENT
        assert view.warning is False
        assert view.actual_hours == 12800


class TestDComplete:
    """Test D - complete an active extension."""

    @pytest.fixture
    def extension_id(self, service, make_draft):
        result = service.create_extension(
            make_draft(service, [("PN001", "SN001", "EO001")]), "tester"
        )
        return result.application.extension_items[0].extension_id

    def test_the_preview_shows_the_latest_actuals(self, service, extension_id):
        preview = service.preview_completion(extension_id)
        assert preview.actual_hours == 12800
        assert preview.actual_cycles == 8390
        assert preview.actual_days == 1570
        assert preview.item.current_hours == 12000

    def test_completion_moves_the_record_to_the_archive(
        self, service, extension_id, settings
    ):
        service.complete_extension(extension_id, "closer")

        assert ActiveExtensionRepository(settings).get_by_id(extension_id) is None
        archived = CompletedExtensionRepository(settings).get_record(extension_id)
        assert archived is not None
        assert archived.item.status is ExtensionStatus.COMPLETED

    def test_the_utilisation_at_completion_is_captured(self, service, extension_id):
        completed = service.complete_extension(extension_id, "closer")
        assert completed.actual_hours_at_completion == 12800
        assert completed.actual_cycles_at_completion == 8390
        assert completed.actual_days_at_completion == 1570
        assert completed.completion_date is not None
        assert completed.completed_by == "closer"
        assert completed.qvd_modified_date_at_completion is not None

    def test_the_original_application_values_are_preserved(self, service, extension_id):
        completed = service.complete_extension(extension_id, "closer")
        assert completed.item.current_hours == 12000
        assert completed.item.extended_hours == 99_000
        assert completed.item.created_by == "tester"

    def test_the_snapshot_does_not_move_when_the_source_moves(
        self, service, extension_id, write_source, settings
    ):
        """Section 44: completion values are historical."""

        service.complete_extension(extension_id, "closer")
        write_source(
            ACTUAL_UTILIZATION, [qvd_data.row("PN001", "SN001", "EO001", hours=99999)]
        )
        service.refresh_source_data()

        archived = CompletedExtensionRepository(settings).get_record(extension_id)
        assert archived.actual_hours_at_completion == 12800

    def test_completing_an_unknown_extension_is_refused(self, service):
        with pytest.raises(RecordNotFoundError):
            service.complete_extension("EXT-2026-000009-001", "closer")

    def test_completion_without_a_source_match_records_unknown_utilisation(
        self, service, extension_id, write_source
    ):
        write_source(ACTUAL_UTILIZATION, [qvd_data.row("PN777", "SN777", "EO777", hours=1)])
        service.refresh_source_data()

        completed = service.complete_extension(extension_id, "closer")
        assert completed.actual_hours_at_completion is None
        assert completed.completion_source_status == ComparisonStatus.NOT_FOUND.value

    def test_completion_is_logged(self, service, extension_id, settings):
        service.complete_extension(extension_id, "closer")
        log = settings.log_file.read_text(encoding="utf-8")
        assert "event=EXTENSION_COMPLETED" in log
        assert f"extension_id={extension_id}" in log


class TestEDelete:
    """Test E - delete an active extension."""

    @pytest.fixture
    def extension_id(self, service, make_draft):
        result = service.create_extension(
            make_draft(service, [("PN001", "SN001", "EO001")]), "tester"
        )
        return result.application.extension_items[0].extension_id

    def test_deletion_moves_the_record_to_the_archive(self, service, extension_id, settings):
        service.delete_extension(extension_id, "remover", "raised in error")

        assert ActiveExtensionRepository(settings).get_by_id(extension_id) is None
        archived = DeletedExtensionRepository(settings).get_record(extension_id)
        assert archived is not None
        assert archived.item.status is ExtensionStatus.DELETED

    def test_deletion_metadata_is_recorded(self, service, extension_id):
        deleted = service.delete_extension(extension_id, "remover", "raised in error")
        assert deleted.deleted_by == "remover"
        assert deleted.deletion_reason == "raised in error"
        assert deleted.deleted_at is not None

    def test_the_original_values_are_preserved_exactly(self, service, extension_id, settings):
        service.delete_extension(extension_id, "remover")
        archived = DeletedExtensionRepository(settings).get_record(extension_id)
        assert archived.item.current_hours == 12000
        assert archived.item.extended_hours == 99_000
        assert archived.item.created_by == "tester"
        assert archived.deletion_reason is None

    def test_nothing_is_discarded_permanently(self, service, extension_id, settings):
        service.delete_extension(extension_id, "remover")
        assert DeletedExtensionRepository(settings).count() == 1

    def test_deleting_an_unknown_extension_is_refused(self, service):
        with pytest.raises(RecordNotFoundError):
            service.delete_extension("EXT-2026-000009-001", "remover")

    def test_a_deleted_identifier_is_never_reissued(self, service, extension_id, make_draft):
        service.delete_extension(extension_id, "remover")
        result = service.create_extension(
            make_draft(service, [("PN002", "SN002", "EO002")]), "tester"
        )
        assert result.application_id == "EXT-2026-000002"

    def test_deletion_is_logged(self, service, extension_id, settings):
        service.delete_extension(extension_id, "remover", "raised in error")
        log = settings.log_file.read_text(encoding="utf-8")
        assert "event=EXTENSION_DELETED" in log


class TestFFailureDuringMove:
    """Test F - a failure while archiving must never lose the active record."""

    @pytest.fixture
    def extension_id(self, service, make_draft):
        result = service.create_extension(
            make_draft(service, [("PN001", "SN001", "EO001")]), "tester"
        )
        return result.application.extension_items[0].extension_id

    def test_a_failed_completion_leaves_the_active_record_intact(
        self, service, extension_id, settings, monkeypatch
    ):
        def explode(*args, **kwargs):
            raise StorageError("simulated archive failure")

        monkeypatch.setattr(service.completed, "stage_append_records", explode)

        with pytest.raises(StorageError):
            service.complete_extension(extension_id, "closer")

        active = ActiveExtensionRepository(settings)
        assert active.get_by_id(extension_id) is not None
        assert active.count() == 1
        assert CompletedExtensionRepository(settings).count() == 0

    def test_a_failed_deletion_leaves_the_active_record_intact(
        self, service, extension_id, settings, monkeypatch
    ):
        def explode(*args, **kwargs):
            raise StorageError("simulated archive failure")

        monkeypatch.setattr(service.deleted, "stage_append_records", explode)

        with pytest.raises(StorageError):
            service.delete_extension(extension_id, "remover")

        assert ActiveExtensionRepository(settings).get_by_id(extension_id) is not None
        assert DeletedExtensionRepository(settings).count() == 0

    def test_a_failure_shortening_the_active_file_keeps_the_record(
        self, service, extension_id, settings, monkeypatch
    ):
        """The archive is written first, so nothing can fall between the two."""

        def explode(*args, **kwargs):
            raise StorageError("simulated active write failure")

        monkeypatch.setattr(service.active, "stage_without", explode)

        with pytest.raises(StorageError):
            service.complete_extension(extension_id, "closer")

        assert ActiveExtensionRepository(settings).get_by_id(extension_id) is not None
        assert CompletedExtensionRepository(settings).count() == 0

    def test_no_temporary_files_survive_a_failure(
        self, service, extension_id, settings, monkeypatch
    ):
        monkeypatch.setattr(
            service.active,
            "stage_without",
            lambda *a, **k: (_ for _ in ()).throw(StorageError("boom")),
        )
        with pytest.raises(StorageError):
            service.complete_extension(extension_id, "closer")

        assert not list(settings.data_dir.rglob("*.tmp.parquet"))

    def test_a_failed_creation_stores_nothing_at_all(
        self, service, make_draft, settings, monkeypatch
    ):
        draft = make_draft(service, [("PN001", "SN001", "EO001")])

        def explode(*args, **kwargs):
            raise StorageError("simulated write failure")

        monkeypatch.setattr(service.active, "stage_append_items", explode)

        with pytest.raises(StorageError):
            service.create_extension(draft, "tester")

        assert ActiveExtensionRepository(settings).count() == 0
        assert not any(settings.documents_dir.iterdir())

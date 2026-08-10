"""Concurrent writers must not overwrite each other (specification section 25)."""

from __future__ import annotations

import threading
import time

import pytest

from app.errors import LockTimeoutError
from app.repositories.active_extension_repository import ActiveExtensionRepository
from app.services.parquet_service import ParquetService
from app.utils.locking import write_lock

SOURCE_ROWS = [
    ("PN001", "SN001", "EO001"),
    ("PN002", "SN002", "EO002"),
    ("PN003", "SN003", "EO003"),
]


class TestWriteLock:
    def test_the_lock_is_exclusive(self, settings):
        acquired = threading.Event()
        release = threading.Event()
        blocked_for = []

        def holder():
            with write_lock(settings.lock_file, timeout=5):
                acquired.set()
                release.wait(timeout=5)

        thread = threading.Thread(target=holder)
        thread.start()
        assert acquired.wait(timeout=5)

        def waiter():
            start = time.monotonic()
            with write_lock(settings.lock_file, timeout=5):
                blocked_for.append(time.monotonic() - start)

        second = threading.Thread(target=waiter)
        second.start()
        time.sleep(0.4)
        release.set()

        thread.join(timeout=5)
        second.join(timeout=5)
        assert blocked_for and blocked_for[0] >= 0.3

    def test_waiting_too_long_reports_a_business_message(self, settings):
        acquired = threading.Event()
        release = threading.Event()

        def holder():
            with write_lock(settings.lock_file, timeout=5):
                acquired.set()
                release.wait(timeout=5)

        thread = threading.Thread(target=holder)
        thread.start()
        assert acquired.wait(timeout=5)

        try:
            with pytest.raises(LockTimeoutError) as exc:
                with write_lock(settings.lock_file, timeout=0.2):
                    pass
            assert "try again" in exc.value.user_message
        finally:
            release.set()
            thread.join(timeout=5)

    def test_the_transaction_helper_uses_the_lock(self, settings):
        service = ParquetService(settings)
        with service.transaction():
            assert settings.lock_file.exists()


class TestConcurrentCreation:
    def test_parallel_applications_do_not_overwrite_each_other(
        self, service, make_draft, settings
    ):
        """Two users must never both write over the same old snapshot."""

        drafts = [make_draft(service, [row]) for row in SOURCE_ROWS]
        errors: list[Exception] = []
        barrier = threading.Barrier(len(drafts))

        def submit(draft, user):
            try:
                barrier.wait(timeout=10)
                service.create_extension(draft, user)
            except Exception as exc:  # collected and asserted on the main thread
                errors.append(exc)

        threads = [
            threading.Thread(target=submit, args=(draft, f"user{index}"))
            for index, draft in enumerate(drafts)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        stored = ActiveExtensionRepository(settings).read_items()
        assert len(stored) == len(SOURCE_ROWS)
        assert {item.pn for item in stored} == {row[0] for row in SOURCE_ROWS}

    def test_every_application_gets_its_own_identifier(self, service, make_draft, settings):
        drafts = [make_draft(service, [row]) for row in SOURCE_ROWS]
        barrier = threading.Barrier(len(drafts))

        def submit(draft):
            barrier.wait(timeout=10)
            service.create_extension(draft, "tester")

        threads = [threading.Thread(target=submit, args=(draft,)) for draft in drafts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        items = ActiveExtensionRepository(settings).read_items()
        application_ids = {item.application_id for item in items}
        extension_ids = {item.extension_id for item in items}
        assert len(application_ids) == len(SOURCE_ROWS)
        assert len(extension_ids) == len(SOURCE_ROWS)

    def test_parallel_completions_leave_a_consistent_database(
        self, service, make_draft, settings
    ):
        created = service.create_extension(
            make_draft(
                service,
                SOURCE_ROWS,
                extended_hours=99_000,
            ),
            "tester",
        )
        extension_ids = [item.extension_id for item in created.application.extension_items]
        barrier = threading.Barrier(len(extension_ids))
        errors: list[Exception] = []

        def complete(extension_id):
            try:
                barrier.wait(timeout=10)
                service.complete_extension(extension_id, "closer")
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=complete, args=(extension_id,))
            for extension_id in extension_ids
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        assert ActiveExtensionRepository(settings).count() == 0
        from app.repositories.completed_extension_repository import (
            CompletedExtensionRepository,
        )

        assert CompletedExtensionRepository(settings).count() == len(extension_ids)

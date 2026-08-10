"""Source data access: mapping, lookup, ambiguity and caching.

Specification sections 6, 7, 12, 14, 55, 58, 63, 64 and 65.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.config.qvd_config import ENGINEERING_ORDER, build_qvd_config
from app.errors import (
    AmbiguousQVDRecordError,
    QVDColumnMappingError,
    QVDSourceUnavailableError,
)
from app.models.enums import ExtensionType
from app.services.qvd_service import QVDService
from app.utils.dates import UTC
from tests.fixtures import qvd_data


class TestLoading:
    def test_rows_are_normalised_to_the_internal_model(self, qvd_service):
        dataset = qvd_service.load_engineering_order_data()
        assert len(dataset) == 3
        record = dataset.lookup("PN001", "SN001", "EO001")
        assert record.pn == "PN001"
        assert record.hours == 12000
        assert record.cycles == 8000
        assert record.days == 1500
        assert record.reference_date == datetime(2026, 8, 1, tzinfo=UTC)
        assert record.modified_date == datetime(2026, 8, 1, tzinfo=UTC)

    def test_raw_column_names_do_not_leak(self, qvd_service):
        record = qvd_service.load_engineering_order_data().records[0]
        assert not hasattr(record, "PART_NUMBER")
        assert set(record.as_dict()) >= {"pn", "sn", "eo", "hours", "cycles", "days"}

    def test_fractional_values_are_not_forced_to_integers(self, qvd_service):
        record = qvd_service.load_engineering_order_data().lookup("PN003", "SN003", "EO003")
        assert record.hours == 9000.5

    def test_hard_time_limits_use_their_own_mapping(self, qvd_service):
        record = qvd_service.load_hard_time_limit_data().lookup("PN010", "SN010", "HTL-500")
        assert record is not None
        assert record.hours == 4000

    def test_each_extension_type_reads_its_own_source(self, qvd_service):
        eo = qvd_service.load_for_extension_type(ExtensionType.ENGINEERING_ORDER)
        htl = qvd_service.load_for_extension_type(ExtensionType.HARD_TIME_LIMIT)
        assert eo.name != htl.name
        assert eo.lookup("PN010", "SN010", "HTL-500") is None
        assert htl.lookup("PN010", "SN010", "HTL-500") is not None


class TestLookup:
    def test_lookup_ignores_whitespace_and_case(self, qvd_service):
        record = qvd_service.lookup_extension_record(
            ExtensionType.ENGINEERING_ORDER, "  pn001 ", "sn001", " eo001"
        )
        assert record is not None
        assert record.pn == "PN001"

    def test_no_match_returns_none(self, qvd_service):
        assert (
            qvd_service.lookup_extension_record(
                ExtensionType.ENGINEERING_ORDER, "PN999", "SN999", "EO999"
            )
            is None
        )

    def test_multiple_matches_raise_instead_of_guessing(self, settings, write_source):
        """Section 65: never arbitrarily select the first record."""

        write_source(
            ENGINEERING_ORDER,
            [
                qvd_data.row("PN001", "SN001", "EO001", hours=12000),
                qvd_data.row("PN001", "SN001", "EO001", hours=12500),
            ],
        )
        service = QVDService(settings)
        with pytest.raises(AmbiguousQVDRecordError) as exc:
            service.lookup_extension_record(
                ExtensionType.ENGINEERING_ORDER, "PN001", "SN001", "EO001"
            )
        assert "Multiple source records" in exc.value.user_message

    def test_matches_returns_every_candidate(self, settings, write_source):
        write_source(
            ENGINEERING_ORDER,
            [
                qvd_data.row("PN001", "SN001", "EO001", hours=12000),
                qvd_data.row("PN001", "SN001", "EO001", hours=12500),
            ],
        )
        dataset = QVDService(settings).load_engineering_order_data()
        assert len(dataset.matches("PN001", "SN001", "EO001")) == 2

    def test_index_is_built_once_for_repeated_lookups(self, qvd_service):
        dataset = qvd_service.load_engineering_order_data()
        assert dataset.index[("PN001", "SN001", "EO001")]


class TestMissingValues:
    def test_source_null_markers_become_none(self, settings, write_source):
        write_source(
            ENGINEERING_ORDER,
            [qvd_data.row("PN500", "SN500", "EO500", hours="N/A", cycles="-", days="")],
        )
        record = QVDService(settings).load_engineering_order_data().records[0]
        assert record.hours is None
        assert record.cycles is None
        assert record.days is None

    def test_zero_is_preserved(self, settings, write_source):
        write_source(
            ENGINEERING_ORDER,
            [qvd_data.row("PN500", "SN500", "EO500", hours=0, cycles=0, days=0)],
        )
        record = QVDService(settings).load_engineering_order_data().records[0]
        assert record.hours == 0
        assert record.hours is not None

    def test_blank_lines_are_skipped(self, settings, write_source):
        write_source(
            ENGINEERING_ORDER,
            [qvd_data.row("PN500", "SN500", "EO500", hours=10), qvd_data.row("", "", "")],
        )
        assert len(QVDService(settings).load_engineering_order_data()) == 1

    def test_unreadable_numbers_do_not_break_the_load(self, settings, write_source):
        write_source(
            ENGINEERING_ORDER, [qvd_data.row("PN500", "SN500", "EO500", hours="twelve")]
        )
        record = QVDService(settings).load_engineering_order_data().records[0]
        assert record.hours is None

    def test_missing_modified_column_falls_back_to_the_file_timestamp(
        self, settings, write_source
    ):
        write_source(
            ENGINEERING_ORDER,
            [qvd_data.row("PN500", "SN500", "EO500", hours=10, modified_date=None)],
        )
        record = QVDService(settings).load_engineering_order_data().records[0]
        assert record.modified_date is not None


class TestConfigurationErrors:
    def test_missing_file_reports_a_business_message(self, settings):
        service = QVDService(settings)
        with pytest.raises(QVDSourceUnavailableError) as exc:
            service.load_engineering_order_data()
        assert "administrator" in exc.value.user_message
        assert "Traceback" not in exc.value.user_message

    def test_missing_required_column_names_the_business_field(
        self, settings, source_files, monkeypatch
    ):
        """Section 53: the user sees 'Hours', never 'KeyError: CURRENT_HOURS'."""

        configs = build_qvd_config(settings)
        broken = configs[ENGINEERING_ORDER]
        columns = dict(broken.columns)
        columns["hours"] = "COLUMN_THAT_DOES_NOT_EXIST"
        from dataclasses import replace

        service = QVDService(
            settings,
            {
                **configs,
                ENGINEERING_ORDER: replace(
                    broken, columns=columns, optional_fields=frozenset()
                ),
            },
        )
        with pytest.raises(QVDColumnMappingError) as exc:
            service.load_engineering_order_data()
        assert "Hours" in exc.value.user_message
        assert "COLUMN_THAT_DOES_NOT_EXIST" not in exc.value.user_message


class TestCaching:
    def test_repeated_loads_reuse_the_cache(self, qvd_service):
        first = qvd_service.load_engineering_order_data()
        second = qvd_service.load_engineering_order_data()
        assert first is second

    def test_a_changed_file_is_reloaded(self, settings, source_files, write_source):
        """Section 63: the cache must not serve stale operational data."""

        service = QVDService(settings)
        assert len(service.load_engineering_order_data()) == 3

        write_source(ENGINEERING_ORDER, [qvd_data.row("PN900", "SN900", "EO900", hours=1)])
        reloaded = service.load_engineering_order_data()
        assert len(reloaded) == 1
        assert reloaded.lookup("PN900", "SN900", "EO900") is not None

    def test_refresh_clears_the_cache(self, qvd_service):
        first = qvd_service.load_engineering_order_data()
        qvd_service.refresh()
        assert qvd_service.load_engineering_order_data() is not first

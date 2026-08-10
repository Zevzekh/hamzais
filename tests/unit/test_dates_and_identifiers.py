"""Date handling (section 56) and identifier generation (sections 4, 16, 48)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.utils.dates import (
    UTC,
    ensure_utc,
    format_date,
    is_after,
    now_utc,
    to_utc_datetime,
)
from app.utils.identifiers import (
    application_id_of,
    build_extension_id,
    build_extension_ids,
    next_application_id,
    parse_application_id,
)


class TestDates:
    def test_naive_datetimes_become_utc(self):
        result = to_utc_datetime(datetime(2026, 8, 10, 12, 0))
        assert result.tzinfo is not None
        assert result == datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    def test_aware_datetimes_are_converted(self):
        other = timezone(timedelta(hours=3))
        result = to_utc_datetime(datetime(2026, 8, 10, 15, 0, tzinfo=other))
        assert result == datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    def test_dates_become_midnight_utc(self):
        assert to_utc_datetime(date(2026, 8, 10)) == datetime(2026, 8, 10, tzinfo=UTC)

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("2026-08-10", datetime(2026, 8, 10, tzinfo=UTC)),
            ("10/08/2026", datetime(2026, 8, 10, tzinfo=UTC)),
            ("10-Aug-2026", datetime(2026, 8, 10, tzinfo=UTC)),
            ("2026-08-10 14:30:00", datetime(2026, 8, 10, 14, 30, tzinfo=UTC)),
        ],
    )
    def test_common_source_formats_parse(self, text, expected):
        assert to_utc_datetime(text) == expected

    def test_missing_values_return_none(self):
        assert to_utc_datetime(None) is None
        assert to_utc_datetime("") is None
        assert to_utc_datetime("N/A") is None

    def test_unparsable_text_raises(self):
        with pytest.raises(ValueError):
            to_utc_datetime("not a date")

    def test_formatting_happens_only_for_display(self):
        assert format_date(datetime(2026, 8, 10, tzinfo=UTC)) == "10-Aug-2026"

    def test_now_is_timezone_aware(self):
        assert now_utc().tzinfo is not None


class TestWarningComparison:
    """Section 31: compare real datetimes, never formatted strings."""

    def test_later_modification_is_after(self):
        created = datetime(2026, 8, 1, tzinfo=UTC)
        modified = datetime(2026, 8, 5, tzinfo=UTC)
        assert is_after(modified, created)

    def test_earlier_modification_is_not_after(self):
        created = datetime(2026, 8, 5, tzinfo=UTC)
        modified = datetime(2026, 8, 1, tzinfo=UTC)
        assert not is_after(modified, created)

    def test_equal_timestamps_are_not_after(self):
        moment = datetime(2026, 8, 5, tzinfo=UTC)
        assert not is_after(moment, moment)

    def test_missing_values_never_warn(self):
        assert not is_after(None, datetime(2026, 8, 5, tzinfo=UTC))
        assert not is_after(datetime(2026, 8, 5, tzinfo=UTC), None)

    def test_string_dates_are_coerced_before_comparison(self):
        assert is_after("2026-08-05", "2026-08-01")
        # A naive string comparison would get this wrong.
        assert is_after("2026-10-01", "2026-09-30")

    def test_naive_and_aware_values_compare(self):
        assert is_after(datetime(2026, 8, 5), ensure_utc(datetime(2026, 8, 1)))


class TestApplicationIds:
    def test_first_id_of_the_year(self):
        assert next_application_id(2026, []) == "EXT-2026-000001"

    def test_sequence_continues_from_the_highest(self):
        existing = ["EXT-2026-000001", "EXT-2026-000009", "EXT-2026-000003"]
        assert next_application_id(2026, existing) == "EXT-2026-000010"

    def test_other_years_do_not_affect_the_sequence(self):
        assert next_application_id(2026, ["EXT-2025-000042"]) == "EXT-2026-000001"

    def test_unparsable_values_are_ignored(self):
        assert next_application_id(2026, ["", None, "rubbish"]) == "EXT-2026-000001"

    def test_prefix_is_configurable(self):
        assert next_application_id(2026, [], prefix="APP") == "APP-2026-000001"

    def test_ids_are_never_reused_after_archiving(self):
        """Archived identifiers must still consume their sequence number."""

        used = {"EXT-2026-000001", "EXT-2026-000002"}
        assert next_application_id(2026, used) == "EXT-2026-000003"

    def test_parse_round_trip(self):
        assert parse_application_id("EXT-2026-000010") == ("EXT", 2026, 10)


class TestExtensionIds:
    def test_row_identifier_layout(self):
        assert build_extension_id("EXT-2026-000010", 1) == "EXT-2026-000010-001"
        assert build_extension_id("EXT-2026-000010", 12) == "EXT-2026-000010-012"

    def test_rows_of_one_application_are_unique_and_ordered(self):
        ids = build_extension_ids("EXT-2026-000010", 3)
        assert ids == [
            "EXT-2026-000010-001",
            "EXT-2026-000010-002",
            "EXT-2026-000010-003",
        ]
        assert len(set(ids)) == 3

    def test_row_numbers_are_one_based(self):
        with pytest.raises(ValueError):
            build_extension_id("EXT-2026-000010", 0)

    def test_owning_application_is_recoverable(self):
        assert application_id_of("EXT-2026-000010-002") == "EXT-2026-000010"

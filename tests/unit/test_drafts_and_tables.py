"""Draft editing (section 10, 60) and list-screen filtering (sections 66, 67)."""

from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO

import pytest

from app.models.drafts import (
    ExtensionApplicationDraft,
    ExtensionRowDraft,
    PendingDocument,
)
from app.models.enums import ComparisonStatus, ExtensionType
from app.models.qvd_record import QVDRecord
from app.models.views import AppliedExtensionView
from app.ui.components.formatting import format_number, status_badge, utilisation_line
from app.ui.components.tables import (
    AppliedFilters,
    filter_views,
    sort_views,
    status_counts,
    views_to_frame,
)
from app.utils.dates import UTC
from tests.unit.test_repositories import make_item


class TestDraftEditing:
    def test_rows_can_be_added_without_limit(self):
        draft = ExtensionApplicationDraft(extension_type=ExtensionType.ENGINEERING_ORDER)
        for _ in range(25):
            draft.add_row()
        assert len(draft.rows) == 25

    def test_each_row_gets_its_own_handle(self):
        draft = ExtensionApplicationDraft()
        first, second = draft.add_row(), draft.add_row()
        assert first.uid != second.uid

    def test_rows_can_be_removed(self):
        draft = ExtensionApplicationDraft()
        draft.add_row().pn = "PN001"
        draft.add_row().pn = "PN002"
        draft.remove_row(0)
        assert [row.pn for row in draft.rows] == ["PN002"]

    def test_removing_an_absent_row_is_harmless(self):
        draft = ExtensionApplicationDraft()
        draft.remove_row(5)
        assert draft.rows == []

    def test_identifiers_are_complete_only_when_all_three_are_present(self):
        row = ExtensionRowDraft(pn="PN001", sn="SN001")
        assert not row.identifiers_complete
        row.eo = "EO001"
        assert row.identifiers_complete

    def test_current_values_come_from_the_source_record(self):
        row = ExtensionRowDraft(pn="PN001", sn="SN001", eo="EO001")
        row.apply_source_record(
            QVDRecord(
                pn="PN001",
                sn="SN001",
                eo="EO001",
                hours=12000,
                cycles=8000,
                days=1500,
                reference_date=datetime(2026, 8, 1, tzinfo=UTC),
                modified_date=datetime(2026, 8, 1, tzinfo=UTC),
            )
        )
        assert row.current_hours == 12000
        assert row.lookup_done
        assert not row.current_values_stale

    def test_editing_an_identifier_invalidates_the_current_values(self):
        row = ExtensionRowDraft(pn="PN001", sn="SN001", eo="EO001")
        row.apply_source_record(QVDRecord(pn="PN001", sn="SN001", eo="EO001", hours=12000))
        row.pn = "PN002"
        assert row.current_values_stale

        row.clear_source_record()
        assert row.current_hours is None
        assert not row.lookup_done

    def test_uploads_are_adapted_without_importing_the_ui_framework(self):
        class FakeUpload(BytesIO):
            name = "report.pdf"
            type = "application/pdf"

        document = PendingDocument.from_upload(FakeUpload(b"data"))
        assert document.filename == "report.pdf"
        assert document.data == b"data"
        assert document.size_bytes == 4
        assert document.content_type == "application/pdf"

    def test_an_unreadable_upload_is_rejected(self):
        with pytest.raises(TypeError):
            PendingDocument.from_upload(object())


def view(
    pn="PN001",
    sn="SN001",
    eo="EO001",
    status=ComparisonStatus.CURRENT,
    actual_hours=12800,
    application_id="EXT-2026-000001",
    extension_id="EXT-2026-000001-001",
    extension_type=ExtensionType.ENGINEERING_ORDER,
    created_at=None,
):
    item = make_item(
        extension_id=extension_id,
        application_id=application_id,
        pn=pn,
        sn=sn,
        eo=eo,
        extension_type=extension_type,
        created_at=created_at or datetime(2026, 8, 1, tzinfo=UTC),
    )
    return AppliedExtensionView(item=item, actual_hours=actual_hours, status=status)


class TestFiltering:
    @pytest.fixture
    def views(self):
        return [
            view(),
            view(pn="PN002", sn="SN002", eo="EO002", extension_id="EXT-2026-000002-001",
                 application_id="EXT-2026-000002", status=ComparisonStatus.SOURCE_CHANGED),
            view(pn="PN003", sn="SN003", eo="EO003", extension_id="EXT-2026-000003-001",
                 application_id="EXT-2026-000003", status=ComparisonStatus.NOT_FOUND,
                 extension_type=ExtensionType.HARD_TIME_LIMIT),
        ]

    def test_no_filter_returns_everything(self, views):
        assert len(filter_views(views, AppliedFilters())) == 3

    def test_filter_by_part_number(self, views):
        assert len(filter_views(views, AppliedFilters(pn="PN002"))) == 1

    def test_filters_ignore_case_and_padding(self, views):
        assert len(filter_views(views, AppliedFilters(pn=" pn002 "))) == 1

    def test_filter_by_application_id(self, views):
        assert len(filter_views(views, AppliedFilters(application_id="EXT-2026-000003"))) == 1

    def test_filter_by_extension_type(self, views):
        selection = filter_views(
            views, AppliedFilters(extension_type=ExtensionType.HARD_TIME_LIMIT)
        )
        assert [v.item.pn for v in selection] == ["PN003"]

    def test_filter_by_status(self, views):
        selection = filter_views(
            views, AppliedFilters(statuses=(ComparisonStatus.SOURCE_CHANGED,))
        )
        assert [v.item.pn for v in selection] == ["PN002"]

    def test_free_text_search_covers_the_key_fields(self, views):
        assert len(filter_views(views, AppliedFilters(search="EO003"))) == 1
        assert len(filter_views(views, AppliedFilters(search="tester"))) == 3

    def test_filters_combine(self, views):
        selection = filter_views(
            views, AppliedFilters(pn="PN00", statuses=(ComparisonStatus.NOT_FOUND,))
        )
        assert [v.item.pn for v in selection] == ["PN003"]


class TestSorting:
    def test_sort_by_part_number(self):
        views = [view(pn="PN003"), view(pn="PN001"), view(pn="PN002")]
        assert [v.item.pn for v in sort_views(views, "pn")] == ["PN001", "PN002", "PN003"]

    def test_sort_descending(self):
        views = [view(pn="PN001"), view(pn="PN003")]
        assert [v.item.pn for v in sort_views(views, "pn", True)] == ["PN003", "PN001"]

    def test_sort_by_application_date(self):
        base = datetime(2026, 8, 1, tzinfo=UTC)
        views = [
            view(pn="LATER", created_at=base + timedelta(days=5)),
            view(pn="EARLIER", created_at=base),
        ]
        assert [v.item.pn for v in sort_views(views, "application_date")] == [
            "EARLIER",
            "LATER",
        ]

    def test_missing_values_sort_last(self):
        views = [view(pn="NONE", actual_hours=None), view(pn="SOME", actual_hours=10)]
        assert [v.item.pn for v in sort_views(views, "actual_hours")] == ["SOME", "NONE"]


class TestDisplay:
    def test_the_table_formats_every_value(self):
        frame = views_to_frame([view()])
        assert frame.loc[0, "Actual Hours"] == "12,800"
        assert frame.loc[0, "Current Hours"] == "12,000"
        assert frame.loc[0, "Application Date"] == "01-Aug-2026 00:00"

    def test_status_is_never_conveyed_by_colour_alone(self):
        """Specification section 35."""

        for status in ComparisonStatus:
            badge = status_badge(status)
            assert badge.split()[0] in {"✓", "⚠", "✖"}
            assert len(badge.split()) > 1

    def test_status_counts_cover_every_state(self):
        counts = status_counts([view(), view(status=ComparisonStatus.NOT_FOUND)])
        assert counts[ComparisonStatus.CURRENT] == 1
        assert counts[ComparisonStatus.NOT_FOUND] == 1
        assert counts[ComparisonStatus.SOURCE_CHANGED] == 0

    def test_missing_numbers_render_as_a_dash_not_a_zero(self):
        assert format_number(None) == "—"
        assert format_number(0) == "0"

    def test_utilisation_line_reads_as_business_text(self):
        assert utilisation_line(12000, 8000, None) == (
            "Hours: 12,000 · Cycles: 8,000 · Days: —"
        )

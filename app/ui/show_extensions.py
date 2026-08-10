"""Show Applied Extensions (specification sections 28 to 37).

Active extensions joined, in memory only, with the latest operational data:
actual utilisation, the source modification date and the resulting review
state.  Nothing on this screen changes stored history.
"""

from __future__ import annotations

import streamlit as st

from app.errors import ExtensionManagementError
from app.models.enums import ComparisonStatus, ExtensionType
from app.ui.components.formatting import format_datetime, format_number, status_badge
from app.ui.components.state import PAGE_HOME, get_service, navigate, show_error
from app.ui.components.tables import (
    SORT_OPTIONS,
    AppliedFilters,
    filter_views,
    sort_views,
    status_counts,
    views_to_frame,
)

_STATE_VIEWS = "applied_views"


def render() -> None:
    header, refresh, home = st.columns([4, 1, 1])
    header.title("Applied Extensions")
    refresh_clicked = refresh.button("Refresh Source Data", help="Re-read the latest operational data")
    if home.button("Home"):
        navigate(PAGE_HOME)

    views = _load_views(force_refresh=refresh_clicked)
    if views is None:
        return

    if not views:
        st.info(
            "There are no active extensions. Use Create New Extension to apply for one."
        )
        return

    _render_summary(views)
    filters = _render_filters()
    selection = filter_views(views, filters)
    selection = _apply_sorting(selection)

    st.caption(f"Showing {len(selection):,} of {len(views):,} active extensions.")
    if not selection:
        st.info("No extensions match the current filters.")
        return

    st.dataframe(views_to_frame(selection), hide_index=True, use_container_width=True)
    _render_attention(selection)
    _render_download(selection)


def _load_views(*, force_refresh: bool):
    service = get_service()
    try:
        with st.spinner("Reading the latest operational data…"):
            views = service.get_active_extensions_with_actuals(force_refresh=force_refresh)
    except ExtensionManagementError as exc:
        show_error(exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        show_error(exc)
        return None
    if force_refresh:
        st.success("Operational data reloaded. Actual values and warnings recalculated.")
    st.session_state[_STATE_VIEWS] = views
    return views


def _render_summary(views) -> None:
    counts = status_counts(views)
    total, current, changed, missing = st.columns(4)
    total.metric("Active extensions", f"{len(views):,}")
    current.metric(
        f"{ComparisonStatus.CURRENT.icon} Current", f"{counts[ComparisonStatus.CURRENT]:,}"
    )
    changed.metric(
        f"{ComparisonStatus.SOURCE_CHANGED.icon} Source changed",
        f"{counts[ComparisonStatus.SOURCE_CHANGED]:,}",
    )
    missing.metric(
        f"{ComparisonStatus.NOT_FOUND.icon} Not found",
        f"{counts[ComparisonStatus.NOT_FOUND]:,}",
    )


def _render_filters() -> AppliedFilters:
    with st.expander("Search and filters", expanded=False):
        search = st.text_input(
            "Search", placeholder="PN, SN, EO, application ID or user", key="applied_search"
        )
        pn_col, sn_col, eo_col = st.columns(3)
        pn = pn_col.text_input("PN", key="applied_pn")
        sn = sn_col.text_input("SN", key="applied_sn")
        eo = eo_col.text_input("EO", key="applied_eo")

        app_col, type_col, status_col = st.columns(3)
        application_id = app_col.text_input("Application ID", key="applied_application")
        extension_type = type_col.selectbox(
            "Extension type",
            [None, *ExtensionType],
            format_func=lambda option: "All" if option is None else option.label,
            key="applied_type",
        )
        statuses = status_col.multiselect(
            "Status",
            list(ComparisonStatus),
            format_func=status_badge,
            key="applied_status",
        )
    return AppliedFilters(
        search=search,
        pn=pn,
        sn=sn,
        eo=eo,
        application_id=application_id,
        extension_type=extension_type,
        statuses=tuple(statuses),
    )


def _apply_sorting(views):
    sort_col, direction_col = st.columns([3, 1])
    field_name = sort_col.selectbox(
        "Sort by",
        [option[0] for option in SORT_OPTIONS],
        format_func=lambda value: dict(SORT_OPTIONS)[value],
        key="applied_sort",
    )
    descending = direction_col.selectbox(
        "Order", ["Ascending", "Descending"], key="applied_order"
    ) == "Descending"
    return sort_views(views, field_name, descending)


def _render_attention(views) -> None:
    """Spell out the rows that need a human look (sections 32, 35, 36)."""

    flagged = [view for view in views if view.warning]
    if not flagged:
        return

    st.subheader("Needs review")
    st.caption(
        "A warning means the source record changed after the extension was created, "
        "or no longer matches. The extension itself is not modified automatically."
    )
    for view in flagged:
        item = view.item
        with st.container(border=True):
            st.markdown(f"{status_badge(view.status)} — **{item.describe()}** ({item.extension_id})")
            if view.detail:
                st.write(view.detail)
            left, middle, right = st.columns(3)
            left.write(f"Applied: {format_datetime(item.created_at)}")
            middle.write(f"Source modified: {format_datetime(view.qvd_modified_date)}")
            right.write(
                "Actual hours: "
                f"{format_number(view.actual_hours)} · "
                f"extended to {format_number(item.extended_hours)}"
            )


def _render_download(views) -> None:
    import csv
    import io

    rows = [view.to_row() for view in views]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if value is None else value for key, value in row.items()})
    st.download_button(
        "Download this view",
        data=buffer.getvalue().encode("utf-8-sig"),
        file_name="applied_extensions.csv",
        mime="text/csv",
    )

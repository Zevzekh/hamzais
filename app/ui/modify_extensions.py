"""Modify Extensions (specification sections 38 to 47).

An active extension can be completed - archived together with the utilisation
at completion - or deleted, which archives it as well.  Both need an explicit
confirmation: a single click never archives a record (section 42).
"""

from __future__ import annotations

import streamlit as st

from app.errors import ExtensionManagementError
from app.models.enums import ComparisonStatus
from app.ui.components.formatting import (
    format_datetime,
    format_number,
    status_badge,
    utilisation_line,
)
from app.ui.components.state import (
    PAGE_HOME,
    current_user,
    get_service,
    navigate,
    show_error,
)
from app.ui.components.tables import AppliedFilters, filter_views, views_to_frame

_STATE_SELECTED = "modify_selected"
_STATE_PENDING = "modify_pending_action"

_MODIFY_COLUMNS = (
    ("status_text", "Status"),
    ("extension_id", "Extension ID"),
    ("pn", "PN"),
    ("sn", "SN"),
    ("eo", "EO"),
    ("extended_hours", "Extended Hours"),
    ("actual_hours", "Actual Hours"),
    ("application_date", "Application Date"),
)


def render() -> None:
    header, home = st.columns([5, 1])
    header.title("Modify Extensions")
    if home.button("Home"):
        _clear_pending()
        navigate(PAGE_HOME)

    service = get_service()
    try:
        views = service.get_active_extensions_with_actuals()
    except ExtensionManagementError as exc:
        show_error(exc)
        return

    if not views:
        st.info("There are no active extensions to modify.")
        return

    search = st.text_input("Search", placeholder="PN, SN, EO or application ID", key="modify_search")
    selection = filter_views(views, AppliedFilters(search=search))
    if not selection:
        st.info("No extensions match the current search.")
        return

    st.dataframe(
        views_to_frame(selection, _MODIFY_COLUMNS), hide_index=True, use_container_width=True
    )

    by_id = {view.extension_id: view for view in selection}
    chosen_id = st.selectbox(
        "Select an extension",
        list(by_id),
        format_func=lambda key: f"{key} — {by_id[key].item.describe()}",
        key=_STATE_SELECTED,
    )
    view = by_id[chosen_id]

    _render_detail(view)

    pending = st.session_state.get(_STATE_PENDING)
    if pending and pending.get("extension_id") == chosen_id:
        if pending["action"] == "delete":
            _render_delete_confirmation(view)
        else:
            _render_complete_confirmation(view)
        return

    complete_col, delete_col = st.columns([1, 5])
    if complete_col.button("Complete", type="primary"):
        st.session_state[_STATE_PENDING] = {"action": "complete", "extension_id": chosen_id}
        st.rerun()
    if delete_col.button("Delete"):
        st.session_state[_STATE_PENDING] = {"action": "delete", "extension_id": chosen_id}
        st.rerun()


def _render_detail(view) -> None:
    item = view.item
    with st.container(border=True):
        st.markdown(f"### {item.describe()}")
        st.caption(f"{item.application_id} · {item.extension_id} · {item.extension_type.label}")
        st.markdown(f"{status_badge(view.status)} — {view.detail or 'Matches the latest operational data.'}")

        current, extended, actual = st.columns(3)
        current.markdown("**Current at application**")
        current.write(utilisation_line(item.current_hours, item.current_cycles, item.current_days))
        extended.markdown("**Extended to**")
        extended.write(
            utilisation_line(item.extended_hours, item.extended_cycles, item.extended_days)
        )
        actual.markdown("**Latest actual**")
        actual.write(utilisation_line(view.actual_hours, view.actual_cycles, view.actual_days))

        st.caption(
            f"Applied {format_datetime(item.created_at)} by {item.created_by} · "
            f"source modified {format_datetime(view.qvd_modified_date)}"
        )


# --- delete ---------------------------------------------------------------
def _render_delete_confirmation(view) -> None:
    item = view.item
    with st.container(border=True):
        st.subheader("Delete extension?")
        st.write(
            "The extension will be removed from the active list and kept in the "
            "deleted archive. Nothing is discarded permanently."
        )
        for label, value in (
            ("Application ID", item.application_id),
            ("Extension ID", item.extension_id),
            ("PN", item.pn),
            ("SN", item.sn),
            ("EO", item.eo),
        ):
            st.markdown(f"**{label}:** {value}")

        reason = st.text_input("Reason (optional)", key=f"delete_reason_{item.extension_id}")

        cancel, confirm = st.columns([1, 4])
        if cancel.button("Cancel", key="delete_cancel"):
            _clear_pending()
            st.rerun()
        if confirm.button("Confirm Delete", type="primary", key="delete_confirm"):
            try:
                get_service().delete_extension(item.extension_id, current_user(), reason or None)
            except ExtensionManagementError as exc:
                show_error(exc)
                return
            _clear_pending()
            st.success(f"{item.extension_id} was deleted and archived.")
            st.rerun()


# --- complete -------------------------------------------------------------
def _render_complete_confirmation(view) -> None:
    item = view.item
    service = get_service()
    try:
        preview = service.preview_completion(item.extension_id)
    except ExtensionManagementError as exc:
        show_error(exc)
        _clear_pending()
        return

    with st.container(border=True):
        st.subheader("Complete extension")
        st.caption(f"{item.application_id} · {item.extension_id}")

        pn_col, sn_col, eo_col = st.columns(3)
        pn_col.markdown(f"**PN**  \n{item.pn}")
        sn_col.markdown(f"**SN**  \n{item.sn}")
        eo_col.markdown(f"**EO**  \n{item.eo}")

        original, extended, actual = st.columns(3)
        original.markdown("**Original current**")
        original.write(utilisation_line(item.current_hours, item.current_cycles, item.current_days))
        extended.markdown("**Extended**")
        extended.write(
            utilisation_line(item.extended_hours, item.extended_cycles, item.extended_days)
        )
        actual.markdown("**Latest actual**")
        actual.write(
            utilisation_line(preview.actual_hours, preview.actual_cycles, preview.actual_days)
        )

        st.markdown(f"**Completion date:** {format_datetime(preview.completion_date)}")

        if preview.source_status is ComparisonStatus.NOT_FOUND:
            st.warning(
                "No single matching operational record was found, so the utilisation at "
                "completion will be recorded as unknown."
            )
        elif preview.source_status is ComparisonStatus.SOURCE_CHANGED:
            st.info("The source record changed after this extension was created.")

        for label, exceeded, actual_value, limit in (
            ("Hours", preview.exceeds_extended_hours, preview.actual_hours, item.extended_hours),
            ("Cycles", preview.exceeds_extended_cycles, preview.actual_cycles, item.extended_cycles),
            ("Days", preview.exceeds_extended_days, preview.actual_days, item.extended_days),
        ):
            if exceeded:
                st.warning(
                    f"Actual {label.lower()} ({format_number(actual_value)}) have reached the "
                    f"extended limit ({format_number(limit)})."
                )

        cancel, confirm = st.columns([1, 4])
        if cancel.button("Cancel", key="complete_cancel"):
            _clear_pending()
            st.rerun()
        if confirm.button("Confirm Completion", type="primary", key="complete_confirm"):
            try:
                service.complete_extension(item.extension_id, current_user())
            except ExtensionManagementError as exc:
                show_error(exc)
                return
            _clear_pending()
            st.success(
                f"{item.extension_id} was completed and archived with the utilisation "
                "recorded at completion."
            )
            st.rerun()


def _clear_pending() -> None:
    st.session_state.pop(_STATE_PENDING, None)

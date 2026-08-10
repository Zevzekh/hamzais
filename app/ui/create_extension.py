"""Create New Extension workflow (specification sections 8 to 20 and 27).

Three steps: choose the extension type, build the application, confirm.
The screen never reads a source file or a database file - it edits a draft and
hands it to the service layer.
"""

from __future__ import annotations

import streamlit as st

from app.errors import ExtensionManagementError, QVDError
from app.models.drafts import ExtensionRowDraft, PendingDocument
from app.models.enums import ExtensionType
from app.ui.components.formatting import format_date, format_number
from app.ui.components.state import (
    PAGE_HOME,
    PAGE_SHOW,
    create_step,
    get_create_result,
    get_draft,
    get_service,
    navigate,
    reset_draft,
    set_create_result,
    set_create_step,
    show_error,
)
from app.utils.dates import to_utc_datetime
from app.utils.file_utils import human_size
from app.utils.normalize import normalize_key, normalize_number

STEP_SELECT_TYPE = 1
STEP_BUILD = 2
STEP_DONE = 3


def render() -> None:
    st.title("Create New Extension")

    step = create_step()
    if step == STEP_DONE and get_create_result() is not None:
        _render_success()
        return
    if step == STEP_SELECT_TYPE:
        _render_type_selection()
        return
    _render_builder()


# --- step 1 ---------------------------------------------------------------
def _render_type_selection() -> None:
    draft = get_draft()
    st.subheader("Select Extension Type")

    options = list(ExtensionType)
    current = draft.extension_type or options[0]
    chosen = st.radio(
        "Extension type",
        options,
        index=options.index(current),
        format_func=lambda option: option.label,
        label_visibility="collapsed",
    )

    st.caption(
        "The extension type determines which technical source data the current "
        "values are read from."
    )

    left, right = st.columns([1, 5])
    if left.button("Continue", type="primary"):
        if draft.extension_type is not chosen:
            draft.extension_type = chosen
            for row in draft.rows:
                row.clear_source_record()
        set_create_step(STEP_BUILD)
        st.rerun()
    if right.button("Cancel"):
        reset_draft()
        navigate(PAGE_HOME)


# --- step 2 ---------------------------------------------------------------
def _render_builder() -> None:
    draft = get_draft()
    if draft.extension_type is None:
        set_create_step(STEP_SELECT_TYPE)
        st.rerun()

    header, action = st.columns([4, 1])
    header.subheader(draft.extension_type.label)
    if action.button("Change type"):
        set_create_step(STEP_SELECT_TYPE)
        st.rerun()

    _render_documents(draft)
    st.divider()
    _render_rows(draft)
    st.divider()
    _render_submit(draft)


def _render_documents(draft) -> None:
    st.subheader("Proof Documents")
    settings = get_service().settings

    uploads = st.file_uploader(
        "Attach the supporting documents for this application",
        accept_multiple_files=True,
        key="proof_uploader",
    )
    # The uploader owns the list: adding and removing there is the single
    # source of truth, which keeps the draft free of duplicates.
    draft.documents = [PendingDocument.from_upload(upload) for upload in (uploads or [])]

    if not draft.documents:
        if settings.require_proof_documents:
            st.info(
                f"At least {settings.min_proof_documents} supporting document is "
                "required before this application can be submitted."
            )
        return

    document_service = get_service().documents
    for document in draft.documents:
        problem = document_service.check_document(document)
        line = f"**{document.filename}** · {human_size(document.size_bytes)}"
        if problem:
            st.warning(f"{line}\n\n{problem}")
        else:
            st.markdown(f"✓ {line}")


def _render_rows(draft) -> None:
    st.subheader("Extension Rows")

    if not draft.rows:
        draft.add_row()

    for position, row in enumerate(draft.rows, start=1):
        _render_row(draft, row, position)

    if st.button("➕ Add Extension Row"):
        draft.add_row()
        st.rerun()


def _render_row(draft, row: ExtensionRowDraft, position: int) -> None:
    with st.container(border=True):
        title, remove = st.columns([5, 1])
        title.markdown(f"**Row {position}**")
        if remove.button("Remove", key=f"remove_{row.uid}", disabled=len(draft.rows) == 1):
            draft.rows.remove(row)
            st.rerun()

        pn_col, sn_col, eo_col, find_col = st.columns([2, 2, 2, 1])
        row.pn = normalize_key(pn_col.text_input("PN", value=row.pn, key=f"pn_{row.uid}")) or ""
        row.sn = normalize_key(sn_col.text_input("SN", value=row.sn, key=f"sn_{row.uid}")) or ""
        row.eo = normalize_key(eo_col.text_input("EO", value=row.eo, key=f"eo_{row.uid}")) or ""
        find_col.markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)
        find_clicked = find_col.button("Find", key=f"find_{row.uid}")

        if row.current_values_stale:
            row.clear_source_record()

        # Look up once all three identifiers are present (section 13).
        if find_clicked or (row.identifiers_complete and not row.lookup_done and not row.lookup_error):
            _lookup_row(draft, row)

        _render_current_values(row)
        _render_extended_values(row)


def _lookup_row(draft, row: ExtensionRowDraft) -> None:
    if not row.identifiers_complete:
        row.clear_source_record("Enter PN, SN and EO to retrieve the current values.")
        return
    try:
        record = get_service().lookup_current_values(
            draft.extension_type, row.pn, row.sn, row.eo
        )
    except QVDError as exc:
        row.clear_source_record(exc.user_message)
        return
    except ExtensionManagementError as exc:
        row.clear_source_record(exc.user_message)
        return

    if record is None:
        row.clear_source_record(
            "No matching source record found for this PN / SN / EO combination."
        )
        return
    row.apply_source_record(record)


def _render_current_values(row: ExtensionRowDraft) -> None:
    st.markdown("**Current** — retrieved from the source data and not editable")
    hours, cycles, days, date = st.columns(4)
    _readonly_field(hours, "Current Hours", format_number(row.current_hours, ""), f"ch_{row.uid}")
    _readonly_field(cycles, "Current Cycles", format_number(row.current_cycles, ""), f"cc_{row.uid}")
    _readonly_field(days, "Current Days", format_number(row.current_days, ""), f"cd_{row.uid}")
    _readonly_field(date, "Current Date", format_date(row.current_date, empty=""), f"cdt_{row.uid}")
    if row.lookup_error:
        st.error(row.lookup_error)


def _readonly_field(column, label: str, value: str, key: str) -> None:
    """Render a disabled field that always shows the latest source value.

    A keyed Streamlit widget keeps whatever it was first given, so the value
    is pushed into session state before the widget is created - otherwise the
    box would stay empty after a lookup.
    """

    st.session_state[key] = value
    column.text_input(label, disabled=True, key=key)


def _render_extended_values(row: ExtensionRowDraft) -> None:
    st.markdown("**Extended** — the limits being applied for")
    hours, cycles, days, date = st.columns(4)

    row.extended_hours = _number_field(hours, "Extended Hours", row.extended_hours, f"eh_{row.uid}")
    row.extended_cycles = _number_field(cycles, "Extended Cycles", row.extended_cycles, f"ec_{row.uid}")
    row.extended_days = _number_field(days, "Extended Days", row.extended_days, f"ed_{row.uid}")

    picked = date.date_input(
        "Extended Date",
        value=row.extended_date.date() if row.extended_date else None,
        format="DD/MM/YYYY",
        key=f"edt_{row.uid}",
    )
    row.extended_date = to_utc_datetime(picked) if picked else None


def _number_field(column, label: str, value, key: str):
    """Free text numeric entry.

    Text rather than a stepper so an empty box stays ``NULL`` and never turns
    into ``0`` - the two mean different things (specification section 15).
    """

    raw = column.text_input(
        label,
        value="" if value is None else str(value),
        key=key,
        placeholder="leave empty if not applicable",
    )
    if not raw.strip():
        return None
    try:
        return normalize_number(raw)
    except ValueError:
        column.caption(f"⚠ {label} must be a number.")
        return raw  # kept as typed so validation reports it


def _render_submit(draft) -> None:
    service = get_service()
    try:
        result = service.validate(draft)
    except ExtensionManagementError as exc:
        show_error(exc)
        return

    for issue in result.warnings:
        st.warning(issue.describe())

    if result.errors:
        with st.expander(f"{len(result.errors)} item(s) still to resolve", expanded=True):
            for issue in result.errors:
                st.markdown(f"- {issue.describe()}")

    apply_col, cancel_col = st.columns([1, 5])
    if apply_col.button("Apply Extension", type="primary", disabled=not result.ok):
        _submit(draft)
    if cancel_col.button("Cancel"):
        reset_draft()
        navigate(PAGE_HOME)


def _submit(draft) -> None:
    service = get_service()
    try:
        with st.spinner("Applying extension…"):
            outcome = service.create_extension(draft, draft.created_by)
    except ExtensionManagementError as exc:
        show_error(exc)
        return
    except Exception as exc:  # pragma: no cover - defensive
        show_error(exc)
        return

    set_create_result(outcome)
    set_create_step(STEP_DONE)
    st.rerun()


# --- step 3 ---------------------------------------------------------------
def _render_success() -> None:
    outcome = get_create_result()
    application = outcome.application

    st.success("Extension created successfully")
    left, right = st.columns(2)
    left.metric("Application ID", application.application_id)
    right.metric("Rows", f"{outcome.row_count:,}")

    for warning in outcome.warnings:
        st.warning(warning)

    if outcome.export_error:
        st.warning(outcome.export_error)
    elif outcome.export_path and outcome.export_path.exists():
        st.download_button(
            "Download Extension File",
            data=outcome.export_path.read_bytes(),
            file_name=outcome.export_path.name,
            mime="application/octet-stream",
            type="primary",
        )

    with st.expander("View application"):
        st.write(f"**Extension type:** {application.extension_type.label}")
        st.write(f"**Applied by:** {application.created_by}")
        st.write(f"**Supporting documents:** {application.document_count}")
        for document in application.proof_documents:
            st.markdown(f"- {document.original_filename}")
        st.dataframe(
            [
                {
                    "Extension ID": item.extension_id,
                    "PN": item.pn,
                    "SN": item.sn,
                    "EO": item.eo,
                    "Current Hours": format_number(item.current_hours),
                    "Extended Hours": format_number(item.extended_hours),
                    "Extended Cycles": format_number(item.extended_cycles),
                    "Extended Days": format_number(item.extended_days),
                    "Extended Date": format_date(item.extended_date),
                }
                for item in application.extension_items
            ],
            hide_index=True,
            use_container_width=True,
        )

    another, applied, home = st.columns([1, 1, 3])
    if another.button("Create Another Extension", type="primary"):
        reset_draft()
        st.rerun()
    if applied.button("Show Applied Extensions"):
        reset_draft()
        navigate(PAGE_SHOW)
    if home.button("Back to home"):
        reset_draft()
        navigate(PAGE_HOME)

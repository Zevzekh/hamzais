"""Home screen - the three workflows (specification section 2).

Business terminology only: no source filenames, no storage details.
"""

from __future__ import annotations

import streamlit as st

from app.ui.components.state import (
    PAGE_CREATE,
    PAGE_MODIFY,
    PAGE_SHOW,
    get_service,
    navigate,
    reset_draft,
    show_error,
)

WORKFLOWS = (
    (
        "Create New Extension",
        "Apply for an extension: choose the type, attach supporting documents "
        "and enter the requested extended limits.",
        PAGE_CREATE,
    ),
    (
        "Show Applied Extensions",
        "Review every extension currently in force against the latest "
        "operational data.",
        PAGE_SHOW,
    ),
    (
        "Modify Extensions",
        "Complete an extension that has run its course, or remove one that is "
        "no longer required.",
        PAGE_MODIFY,
    ),
)


def render() -> None:
    st.title("Extension Management")
    st.caption("Apply for, review and close out technical extensions.")

    columns = st.columns(len(WORKFLOWS), gap="large")
    for column, (title, description, page) in zip(columns, WORKFLOWS):
        with column:
            st.subheader(title)
            st.write(description)
            if st.button(title, key=f"home_{page}", use_container_width=True, type="primary"):
                if page == PAGE_CREATE:
                    reset_draft()
                navigate(page)

    st.divider()
    _render_summary()


def _render_summary() -> None:
    """A small, read-only overview so the landing page is not empty."""

    try:
        service = get_service()
        active = len(service.get_active_extensions())
        completed = len(service.get_completed_extensions())
        deleted = len(service.get_deleted_extensions())
    except Exception as exc:  # the home page must still render
        show_error(exc)
        return

    left, middle, right = st.columns(3)
    left.metric("Active extensions", f"{active:,}")
    middle.metric("Completed", f"{completed:,}")
    right.metric("Deleted", f"{deleted:,}")

"""Streamlit shell: page configuration, sidebar and routing.

The UI framework is confined to ``app/ui``; every business decision lives in
the service layer (specification section 3).
"""

from __future__ import annotations

import streamlit as st

from app.ui import create_extension, home, modify_extensions, show_extensions
from app.ui.components.state import (
    PAGE_CREATE,
    PAGE_HOME,
    PAGE_MODIFY,
    PAGE_SHOW,
    current_page,
    current_user,
    go_to,
    reset_draft,
    set_current_user,
)

PAGES = {
    PAGE_HOME: ("Home", home.render),
    PAGE_CREATE: ("Create New Extension", create_extension.render),
    PAGE_SHOW: ("Show Applied Extensions", show_extensions.render),
    PAGE_MODIFY: ("Modify Extensions", modify_extensions.render),
}


def _render_sidebar() -> None:
    with st.sidebar:
        st.header("Extension Management")

        user = st.text_input("User", value=current_user(), help="Recorded against every action")
        set_current_user(user)

        st.divider()
        for page, (label, _) in PAGES.items():
            if st.button(label, key=f"nav_{page}", use_container_width=True):
                if page == PAGE_CREATE and current_page() != PAGE_CREATE:
                    reset_draft()
                go_to(page)
                st.rerun()


def run() -> None:
    st.set_page_config(
        page_title="Extension Management",
        page_icon="🛠",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _render_sidebar()
    _, render = PAGES.get(current_page(), PAGES[PAGE_HOME])
    render()

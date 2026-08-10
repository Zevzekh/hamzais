"""Session state and service wiring for the Streamlit UI.

The screens never construct repositories or read files: they ask for the
service built here (specification sections 60 and 82).
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.config.settings import Settings, get_settings
from app.models.drafts import ExtensionApplicationDraft
from app.services.extension_service import ExtensionService
from app.utils.logging_utils import AuditEvent, configure_logging, get_logger, log_event

PAGE_HOME = "home"
PAGE_CREATE = "create"
PAGE_SHOW = "show"
PAGE_MODIFY = "modify"

_STATE_PAGE = "page"
_STATE_USER = "current_user"
_STATE_DRAFT = "draft"
_STATE_CREATE_STEP = "create_step"
_STATE_RESULT = "create_result"


@st.cache_resource(show_spinner=False)
def _build_service() -> ExtensionService:
    settings = get_settings()
    settings.ensure_directories()
    configure_logging(settings)
    return ExtensionService.create_default(settings)


def get_service() -> ExtensionService:
    """The single application service instance for this server process."""

    return _build_service()


def get_app_settings() -> Settings:
    return get_settings()


def current_user() -> str:
    """Who is using the application.

    The authentication source is still to be decided (specification section
    87), so the identity is configurable and captured once per session.
    """

    if _STATE_USER not in st.session_state:
        st.session_state[_STATE_USER] = get_settings().default_user
        log_event(get_logger("ui"), AuditEvent.USER_LOGIN, user=st.session_state[_STATE_USER])
    return st.session_state[_STATE_USER]


def set_current_user(user: str) -> None:
    user = (user or "").strip() or get_settings().default_user
    if user != st.session_state.get(_STATE_USER):
        st.session_state[_STATE_USER] = user
        log_event(get_logger("ui"), AuditEvent.USER_LOGIN, user=user)


# --- navigation ----------------------------------------------------------
def current_page() -> str:
    return st.session_state.get(_STATE_PAGE, PAGE_HOME)


def go_to(page: str) -> None:
    st.session_state[_STATE_PAGE] = page


def navigate(page: str) -> None:
    """Change page and rerun immediately."""

    go_to(page)
    st.rerun()


# --- create workflow state ------------------------------------------------
def get_draft() -> ExtensionApplicationDraft:
    draft = st.session_state.get(_STATE_DRAFT)
    if not isinstance(draft, ExtensionApplicationDraft):
        draft = ExtensionApplicationDraft(created_by=current_user())
        st.session_state[_STATE_DRAFT] = draft
    return draft


def reset_draft() -> ExtensionApplicationDraft:
    draft = ExtensionApplicationDraft(created_by=current_user())
    st.session_state[_STATE_DRAFT] = draft
    st.session_state[_STATE_CREATE_STEP] = 1
    st.session_state.pop(_STATE_RESULT, None)
    return draft


def create_step() -> int:
    return int(st.session_state.get(_STATE_CREATE_STEP, 1))


def set_create_step(step: int) -> None:
    st.session_state[_STATE_CREATE_STEP] = step


def set_create_result(result: Any) -> None:
    st.session_state[_STATE_RESULT] = result


def get_create_result() -> Any:
    return st.session_state.get(_STATE_RESULT)


# --- shared UI helpers ----------------------------------------------------
def show_error(exc: Exception) -> None:
    """Show the business message and log the technical one (section 53)."""

    user_message = getattr(exc, "user_message", None)
    if user_message:
        st.error(user_message)
    else:
        st.error(
            "An unexpected application error occurred. "
            "Please contact the application administrator."
        )
    get_logger("ui").exception("unhandled error in the user interface: %s", exc)

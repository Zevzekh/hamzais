"""Application error hierarchy.

Every error carries two messages:

``message``
    The technical detail. This goes to the log files.
``user_message``
    A business readable sentence that may be shown in the user interface.

UI code must only ever display ``user_message`` (see section 53 of the
specification: users should never see ``KeyError: QVD_COL_18``).
"""

from __future__ import annotations

from typing import Any

ADMIN_HINT = "Please contact the application administrator."


class ExtensionManagementError(Exception):
    """Base class for all application errors."""

    default_user_message = f"An unexpected application error occurred. {ADMIN_HINT}"

    def __init__(
        self,
        message: str | None = None,
        *,
        user_message: str | None = None,
        **context: Any,
    ) -> None:
        self.context = context
        self.user_message = user_message or self.default_user_message
        super().__init__(message or self.user_message)

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = super().__str__()
        if not self.context:
            return base
        details = " ".join(f"{key}={value}" for key, value in sorted(self.context.items()))
        return f"{base} ({details})"


class ConfigurationError(ExtensionManagementError):
    default_user_message = (
        f"The application is not configured correctly. {ADMIN_HINT}"
    )


class QVDError(ExtensionManagementError):
    default_user_message = f"The source data could not be read. {ADMIN_HINT}"


class QVDSourceUnavailableError(QVDError):
    default_user_message = (
        f"The required source data file is currently unavailable. {ADMIN_HINT}"
    )


class QVDReaderNotAvailableError(QVDError):
    default_user_message = (
        "The source data format configured for this application cannot be read by "
        f"this installation. {ADMIN_HINT}"
    )


class QVDColumnMappingError(QVDError):
    default_user_message = (
        f"A required field is missing from the source data. {ADMIN_HINT}"
    )


class AmbiguousQVDRecordError(QVDError):
    default_user_message = (
        "Multiple source records were found for this PN / SN / EO combination. "
        "Review the source data before applying an extension."
    )


class RecordNotFoundError(ExtensionManagementError):
    default_user_message = "The requested extension could not be found."


class ValidationFailedError(ExtensionManagementError):
    default_user_message = (
        "The extension could not be saved because some information is missing or invalid."
    )

    def __init__(self, message: str | None = None, *, issues=None, **kwargs: Any) -> None:
        self.issues = list(issues or [])
        super().__init__(message, **kwargs)


class DuplicateExtensionError(ExtensionManagementError):
    default_user_message = (
        "An active extension already exists for this PN / SN / EO combination."
    )


class StorageError(ExtensionManagementError):
    default_user_message = (
        f"The extension database could not be updated. No changes were saved. {ADMIN_HINT}"
    )


class LockTimeoutError(StorageError):
    default_user_message = (
        "Another user is currently saving changes. Please try again in a moment."
    )


class DocumentError(ExtensionManagementError):
    default_user_message = "The supporting document could not be stored."


class ExportError(ExtensionManagementError):
    default_user_message = (
        f"The extension export file could not be generated. {ADMIN_HINT}"
    )

"""Proof document storage (specification sections 9 and 59).

Files live on disk under ``data/documents/<application_id>/``; only metadata
goes into the database.  Filenames are sanitised, collisions are avoided and
nothing can escape the documents root.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
from pathlib import Path
from typing import Sequence

from app.config.settings import Settings, get_settings
from app.errors import DocumentError
from app.models.drafts import PendingDocument
from app.models.extension import ProofDocument
from app.repositories.document_repository import DocumentRepository
from app.utils.dates import now_utc
from app.utils.file_utils import (
    ensure_directory,
    file_extension,
    human_size,
    is_within,
    relative_to_root,
    sanitize_filename,
    unique_path,
)
from app.utils.identifiers import new_document_id
from app.utils.logging_utils import AuditEvent, get_logger, log_event


class DocumentService:
    """Validates and stores supporting documents."""

    def __init__(
        self,
        settings: Settings | None = None,
        repository: DocumentRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or DocumentRepository(self.settings)
        self.logger = get_logger("documents")

    # --- policy ----------------------------------------------------------
    def check_document(self, document: PendingDocument) -> str | None:
        """Return a business readable problem, or ``None`` when acceptable."""

        name = document.filename or "(unnamed)"
        if document.size_bytes == 0:
            return f"'{name}' is empty and cannot be attached."

        allowed = tuple(self.settings.allowed_document_extensions)
        extension = file_extension(document.filename)
        if allowed and extension not in allowed:
            readable = ", ".join(allowed)
            return (
                f"'{name}' has an unsupported file type. "
                f"Supported types are: {readable}."
            )

        limit = self.settings.max_document_size_bytes
        if limit and document.size_bytes > limit:
            return (
                f"'{name}' is {human_size(document.size_bytes)}, which exceeds the "
                f"{human_size(limit)} limit for supporting documents."
            )
        return None

    def validate_documents(self, documents: Sequence[PendingDocument]) -> list[str]:
        problems = [
            problem
            for problem in (self.check_document(document) for document in documents)
            if problem
        ]
        for problem in problems:
            log_event(self.logger, AuditEvent.DOCUMENT_REJECTED, reason=problem[:80])
        return problems

    # --- storage ---------------------------------------------------------
    def application_directory(self, application_id: str) -> Path:
        safe_id = sanitize_filename(application_id, fallback="application")
        return self.settings.documents_dir / safe_id

    def save_documents(
        self,
        application_id: str,
        documents: Sequence[PendingDocument],
        uploaded_by: str,
        *,
        register: bool = True,
    ) -> list[ProofDocument]:
        """Write files to disk and record their metadata.

        Raises :class:`DocumentError` if anything fails; anything already
        written for this application is rolled back so a failed submission
        leaves no half-stored evidence.
        """

        if not documents:
            return []

        problems = self.validate_documents(documents)
        if problems:
            raise DocumentError(
                "; ".join(problems),
                user_message=problems[0],
                application_id=application_id,
            )

        directory = ensure_directory(self.application_directory(application_id))
        if not is_within(directory, self.settings.documents_dir):
            raise DocumentError(
                f"refusing to store documents outside the documents root: {directory}",
                application_id=application_id,
            )

        stored: list[ProofDocument] = []
        written_paths: list[Path] = []
        uploaded_at = now_utc()
        try:
            for sequence, document in enumerate(documents, start=1):
                destination = unique_path(directory, document.filename)
                destination.write_bytes(document.data)
                written_paths.append(destination)
                stored.append(
                    ProofDocument(
                        document_id=new_document_id(application_id, sequence),
                        application_id=application_id,
                        original_filename=document.filename,
                        stored_filename=destination.name,
                        relative_path=relative_to_root(destination, self.settings.data_dir),
                        size_bytes=document.size_bytes,
                        content_type=document.content_type,
                        uploaded_at=uploaded_at,
                        uploaded_by=uploaded_by,
                    )
                )
        except OSError as exc:
            for path in written_paths:
                with contextlib.suppress(OSError):
                    path.unlink()
            log_event(
                self.logger,
                AuditEvent.DOCUMENT_REJECTED,
                level=logging.ERROR,
                application_id=application_id,
                error=type(exc).__name__,
            )
            raise DocumentError(
                f"could not store supporting documents for {application_id}",
                user_message=(
                    "The supporting documents could not be stored. No extension was created."
                ),
                application_id=application_id,
            ) from exc

        if register:
            self.repository.append_documents(stored)

        for document in stored:
            log_event(
                self.logger,
                AuditEvent.DOCUMENT_UPLOADED,
                application_id=application_id,
                document_id=document.document_id,
                filename=document.stored_filename,
                size_bytes=document.size_bytes,
                user=uploaded_by,
            )
        return stored

    def discard_documents(self, application_id: str) -> None:
        """Remove files written for an application whose save failed."""

        directory = self.application_directory(application_id)
        if directory.exists() and is_within(directory, self.settings.documents_dir):
            with contextlib.suppress(OSError):
                shutil.rmtree(directory)

    # --- reading ---------------------------------------------------------
    def documents_for_application(self, application_id: str) -> list[ProofDocument]:
        return self.repository.documents_for_application(application_id)

    def absolute_path(self, document: ProofDocument) -> Path:
        return self.settings.data_dir / document.relative_path

    def read_document(self, document: ProofDocument) -> bytes:
        path = self.absolute_path(document)
        if not is_within(path, self.settings.documents_dir) or not path.exists():
            raise DocumentError(
                f"stored document missing: {path}",
                user_message=(
                    f"'{document.original_filename}' could not be opened because the "
                    "stored file is no longer available."
                ),
                document_id=document.document_id,
            )
        return path.read_bytes()

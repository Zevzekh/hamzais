"""The application's business orchestration layer.

Every workflow the UI offers goes through this service (specification
sections 60, 61 and 83).  It owns the transaction boundaries, the historical
snapshots and the audit trail; the screens only render what it returns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.config.settings import Settings, get_settings
from app.errors import (
    AmbiguousQVDRecordError,
    ExportError,
    RecordNotFoundError,
    ValidationFailedError,
)
from app.models.archive import CompletedExtension, DeletedExtension
from app.models.drafts import ExtensionApplicationDraft
from app.models.enums import ComparisonStatus, ExtensionStatus, ExtensionType, LimitStatus
from app.models.extension import ExtensionApplication, ProofDocument
from app.models.extension_item import ExtensionItem, encode_document_reference
from app.models.qvd_record import QVDRecord
from app.models.views import AppliedExtensionView, CompletionPreview
from app.repositories.active_extension_repository import ActiveExtensionRepository
from app.repositories.completed_extension_repository import CompletedExtensionRepository
from app.repositories.deleted_extension_repository import DeletedExtensionRepository
from app.repositories.document_repository import DocumentRepository
from app.services.document_service import DocumentService
from app.services.export_service import ExportService
from app.services.parquet_service import ParquetService, StagedWrite
from app.services.qvd_service import QVDService
from app.services.validation_service import ValidationResult, ValidationService
from app.utils.dates import is_after, now_utc
from app.utils.identifiers import build_extension_id, next_application_id
from app.utils.logging_utils import AuditEvent, configure_logging, get_logger, log_event


@dataclass(frozen=True)
class CreateExtensionResult:
    """What the Create workflow produced (specification section 27)."""

    application: ExtensionApplication
    export_path: Path | None = None
    export_error: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def application_id(self) -> str:
        return self.application.application_id

    @property
    def row_count(self) -> int:
        return self.application.row_count


class ExtensionService:
    """Create, review, complete and delete extensions."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        qvd_service: QVDService | None = None,
        active_repository: ActiveExtensionRepository | None = None,
        completed_repository: CompletedExtensionRepository | None = None,
        deleted_repository: DeletedExtensionRepository | None = None,
        document_repository: DocumentRepository | None = None,
        document_service: DocumentService | None = None,
        validation_service: ValidationService | None = None,
        export_service: ExportService | None = None,
        parquet_service: ParquetService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        # Point the audit log at this configuration's log file before any
        # component starts emitting events.
        configure_logging(self.settings)

        self.parquet = parquet_service or ParquetService(self.settings)
        self.qvd = qvd_service or QVDService(self.settings)
        self.active = active_repository or ActiveExtensionRepository(self.settings, self.parquet)
        self.completed = completed_repository or CompletedExtensionRepository(
            self.settings, self.parquet
        )
        self.deleted = deleted_repository or DeletedExtensionRepository(self.settings, self.parquet)
        self.documents_repo = document_repository or DocumentRepository(self.settings, self.parquet)
        self.documents = document_service or DocumentService(self.settings, self.documents_repo)
        self.validation = validation_service or ValidationService(
            self.settings, self.qvd, self.active, self.documents
        )
        self.exports = export_service or ExportService(self.settings)
        self.logger = get_logger("extensions")

    # -- lookups -----------------------------------------------------------
    def lookup_current_values(
        self, extension_type: ExtensionType, pn: str, sn: str, eo: str
    ) -> QVDRecord | None:
        """Current values for one row, straight from the source data."""

        return self.qvd.lookup_extension_record(extension_type, pn, sn, eo)

    def refresh_source_data(self) -> None:
        """Force the next read to hit the source files again (section 68)."""

        self.qvd.refresh()

    # -- create ------------------------------------------------------------
    def validate(self, draft: ExtensionApplicationDraft) -> ValidationResult:
        return self.validation.validate_application(draft)

    def create_extension(
        self,
        draft: ExtensionApplicationDraft,
        created_by: str | None = None,
    ) -> CreateExtensionResult:
        """Turn a validated draft into stored records plus an export file.

        Follows the submission sequence of section 19: identifiers, timestamp,
        user, frozen source values, documents, database, export.
        """

        user = created_by or draft.created_by or self.settings.default_user
        result = self.validate(draft)
        if not result.ok:
            raise ValidationFailedError(
                "; ".join(result.error_messages()),
                issues=result.errors,
                user_message=result.error_messages()[0],
            )

        assert draft.extension_type is not None  # guaranteed by validation
        created_at = now_utc()

        with self.parquet.transaction():
            existing_active = self.active.read_all()
            existing_documents = self.documents_repo.read_all()
            application_id = self._next_application_id(created_at, existing_active)

            documents = self.documents.save_documents(
                application_id, draft.documents, user, register=False
            )
            document_reference = encode_document_reference(
                [document.relative_path for document in documents]
            )

            staged: list[StagedWrite] = []
            try:
                items = self._build_items(
                    draft, application_id, created_at, user, document_reference
                )
                staged.append(self.active.stage_append_items(items, existing_active))
                if documents:
                    staged.append(
                        self.documents_repo.stage_append_documents(documents, existing_documents)
                    )
                self.parquet.commit(staged)
            except Exception:
                self.parquet.discard(staged)
                self.documents.discard_documents(application_id)
                log_event(
                    self.logger,
                    AuditEvent.PARQUET_WRITE_FAILED,
                    level=logging.ERROR,
                    application_id=application_id,
                    user=user,
                )
                raise

        application = ExtensionApplication(
            application_id=application_id,
            extension_type=draft.extension_type,
            created_at=created_at,
            created_by=user,
            proof_documents=tuple(documents),
            extension_items=tuple(items),
        )
        for item in items:
            log_event(
                self.logger,
                AuditEvent.EXTENSION_CREATED,
                application_id=application_id,
                extension_id=item.extension_id,
                extension_type=item.extension_type.value,
                pn=item.pn,
                sn=item.sn,
                eo=item.eo,
                user=user,
            )

        export_path: Path | None = None
        export_error: str | None = None
        try:
            export_path = self.exports.export_application(application)
        except ExportError as exc:
            export_error = exc.user_message
            self.logger.error("export failed for %s: %s", application_id, exc)

        return CreateExtensionResult(
            application=application,
            export_path=export_path,
            export_error=export_error,
            warnings=tuple(issue.describe() for issue in result.warnings),
        )

    def _next_application_id(
        self, created_at: datetime, existing_active: Sequence[Mapping[str, Any]]
    ) -> str:
        """Never reuse an identifier, including ones already archived."""

        used = {
            str(row.get("application_id"))
            for row in existing_active
            if row.get("application_id")
        }
        used |= self.completed.application_ids()
        used |= self.deleted.application_ids()
        return next_application_id(
            created_at.year, used, prefix=self.settings.application_id_prefix
        )

    def _build_items(
        self,
        draft: ExtensionApplicationDraft,
        application_id: str,
        created_at: datetime,
        user: str,
        document_reference: str | None,
    ) -> list[ExtensionItem]:
        """Freeze the source values into immutable rows (sections 19 and 20)."""

        items: list[ExtensionItem] = []
        for position, row in enumerate(draft.rows, start=1):
            row.normalized()
            record = self.qvd.lookup_extension_record(
                draft.extension_type, row.pn, row.sn, row.eo
            )
            if record is None:
                raise ValidationFailedError(
                    f"row {position} no longer matches a source record",
                    user_message=(
                        f"Row {position}: the source record for {row.pn} / {row.sn} / {row.eo} "
                        "is no longer available. Review the row and try again."
                    ),
                )
            items.append(
                ExtensionItem(
                    extension_id=build_extension_id(application_id, position),
                    application_id=application_id,
                    extension_type=draft.extension_type,
                    pn=row.pn,
                    sn=row.sn,
                    eo=row.eo,
                    current_hours=record.hours,
                    current_cycles=record.cycles,
                    current_days=record.days,
                    current_date=record.reference_date,
                    extended_hours=row.extended_hours,
                    extended_cycles=row.extended_cycles,
                    extended_days=row.extended_days,
                    extended_date=row.extended_date,
                    qvd_modified_date_at_application=record.modified_date,
                    created_at=created_at,
                    created_by=user,
                    proof_document_reference=document_reference,
                    status=ExtensionStatus.ACTIVE,
                )
            )
        return items

    # -- read ---------------------------------------------------------------
    def get_active_extensions(self) -> list[ExtensionItem]:
        return self.active.read_items()

    def get_active_extensions_with_actuals(
        self, *, force_refresh: bool = False
    ) -> list[AppliedExtensionView]:
        """Join active extensions with the latest operational data (section 28).

        Nothing is written back: the actual values exist only in this view
        (sections 33 and 85.14).
        """

        items = self.active.read_items()
        if not items:
            return []
        index = self.qvd.actual_records_by_key(force_reload=force_refresh)
        return [self._build_view(item, index.get(item.key, ())) for item in items]

    def _build_view(
        self, item: ExtensionItem, matches: Sequence[QVDRecord]
    ) -> AppliedExtensionView:
        if not matches:
            return AppliedExtensionView(
                item=item,
                status=ComparisonStatus.NOT_FOUND,
                detail="No matching record in the latest operational data.",
            )
        if len(matches) > 1:
            # Picking one arbitrarily would be a guess (section 65), so the row
            # is surfaced for review instead.
            return AppliedExtensionView(
                item=item,
                status=ComparisonStatus.NOT_FOUND,
                detail=(
                    f"{len(matches)} operational records match this PN / SN / EO. "
                    "Review the source data."
                ),
            )

        record = matches[0]
        changed = is_after(record.modified_date, item.created_at)
        return AppliedExtensionView(
            item=item,
            actual_hours=record.hours,
            actual_cycles=record.cycles,
            actual_days=record.days,
            qvd_modified_date=record.modified_date,
            status=ComparisonStatus.SOURCE_CHANGED if changed else ComparisonStatus.CURRENT,
            limit_status=self._limit_status(item, record),
            detail=(
                "The source record was modified after this extension was created."
                if changed
                else None
            ),
        )

    def _limit_status(self, item: ExtensionItem, record: QVDRecord) -> LimitStatus:
        """Optional utilisation monitoring (section 37).

        Off unless enabled in configuration, and purely informational: the
        application never completes an extension by itself.
        """

        if not getattr(self.settings, "limit_monitoring_enabled", False):
            return LimitStatus.UNKNOWN

        ratio = getattr(self.settings, "approaching_limit_ratio", 0.9)
        pairs = (
            (record.hours, item.extended_hours),
            (record.cycles, item.extended_cycles),
            (record.days, item.extended_days),
        )
        comparable = [(a, b) for a, b in pairs if a is not None and b not in (None, 0)]
        if not comparable:
            return LimitStatus.UNKNOWN
        if any(actual >= limit for actual, limit in comparable):
            return LimitStatus.LIMIT_EXCEEDED
        if any(actual >= limit * ratio for actual, limit in comparable):
            return LimitStatus.APPROACHING_LIMIT
        return LimitStatus.WITHIN_LIMIT

    def get_extension(self, extension_id: str) -> ExtensionItem:
        item = self.active.get_item(extension_id)
        if item is None:
            raise RecordNotFoundError(
                f"no active extension {extension_id}",
                user_message=(
                    "That extension is no longer active. Refresh the list and try again."
                ),
                extension_id=extension_id,
            )
        return item

    def get_application(self, application_id: str) -> ExtensionApplication:
        """Rebuild an application header from stored rows."""

        items = self.active.items_for_application(application_id)
        if not items:
            completed = [
                record.item
                for record in self.completed.read_records_typed()
                if record.item.application_id == application_id
            ]
            deleted = [
                record.item
                for record in self.deleted.read_records_typed()
                if record.item.application_id == application_id
            ]
            items = completed + deleted
        if not items:
            raise RecordNotFoundError(
                f"no application {application_id}",
                user_message="That application could not be found.",
                application_id=application_id,
            )
        return ExtensionApplication.from_items(
            items, self.documents.documents_for_application(application_id)
        )

    def get_completed_extensions(self) -> list[CompletedExtension]:
        return self.completed.read_records_typed()

    def get_deleted_extensions(self) -> list[DeletedExtension]:
        return self.deleted.read_records_typed()

    def get_documents(self, application_id: str) -> list[ProofDocument]:
        return self.documents.documents_for_application(application_id)

    # -- complete -----------------------------------------------------------
    def preview_completion(self, extension_id: str) -> CompletionPreview:
        """Everything the confirmation screen needs (section 46)."""

        item = self.get_extension(extension_id)
        record, status, _ = self._latest_actual(item)
        return CompletionPreview(
            item=item,
            actual_hours=record.hours if record else None,
            actual_cycles=record.cycles if record else None,
            actual_days=record.days if record else None,
            qvd_modified_date=record.modified_date if record else None,
            completion_date=now_utc(),
            source_status=status,
        )

    def complete_extension(
        self, extension_id: str, completed_by: str | None = None
    ) -> CompletedExtension:
        """Archive an active extension together with its utilisation.

        The completion snapshot is permanent: later source changes never
        rewrite it (sections 44 and 85.13).
        """

        user = completed_by or self.settings.default_user
        completion_date = now_utc()

        with self.parquet.transaction():
            active_rows = self.active.read_all()
            row = self.active.find_by_id(active_rows, extension_id)
            if row is None:
                raise RecordNotFoundError(
                    f"no active extension {extension_id}",
                    user_message=(
                        "That extension is no longer active. Refresh the list and try again."
                    ),
                    extension_id=extension_id,
                )

            item = ExtensionItem.from_row(row)
            record, status, _ = self._latest_actual(item)
            completed = CompletedExtension(
                item=item,
                completion_date=completion_date,
                completed_by=user,
                actual_hours_at_completion=record.hours if record else None,
                actual_cycles_at_completion=record.cycles if record else None,
                actual_days_at_completion=record.days if record else None,
                qvd_modified_date_at_completion=record.modified_date if record else None,
                completion_source_status=status.value,
            )
            self._move(
                item,
                destination_staged=self.completed.stage_append_records([completed]),
                active_rows=active_rows,
            )

        log_event(
            self.logger,
            AuditEvent.EXTENSION_COMPLETED,
            application_id=item.application_id,
            extension_id=item.extension_id,
            pn=item.pn,
            sn=item.sn,
            eo=item.eo,
            actual_hours=completed.actual_hours_at_completion,
            actual_cycles=completed.actual_cycles_at_completion,
            actual_days=completed.actual_days_at_completion,
            source_status=status.value,
            user=user,
        )
        return completed

    # -- delete -------------------------------------------------------------
    def delete_extension(
        self,
        extension_id: str,
        deleted_by: str | None = None,
        deletion_reason: str | None = None,
    ) -> DeletedExtension:
        """Archive an active extension. History is never discarded (section 40)."""

        user = deleted_by or self.settings.default_user
        deleted_at = now_utc()

        with self.parquet.transaction():
            active_rows = self.active.read_all()
            row = self.active.find_by_id(active_rows, extension_id)
            if row is None:
                raise RecordNotFoundError(
                    f"no active extension {extension_id}",
                    user_message=(
                        "That extension is no longer active. Refresh the list and try again."
                    ),
                    extension_id=extension_id,
                )

            item = ExtensionItem.from_row(row)
            deleted = DeletedExtension(
                item=item,
                deleted_at=deleted_at,
                deleted_by=user,
                deletion_reason=(deletion_reason or None),
            )
            self._move(
                item,
                destination_staged=self.deleted.stage_append_records([deleted]),
                active_rows=active_rows,
            )

        log_event(
            self.logger,
            AuditEvent.EXTENSION_DELETED,
            application_id=item.application_id,
            extension_id=item.extension_id,
            pn=item.pn,
            sn=item.sn,
            eo=item.eo,
            reason=(deletion_reason or "-")[:60],
            user=user,
        )
        return deleted

    # -- shared move machinery ---------------------------------------------
    def _move(
        self,
        item: ExtensionItem,
        destination_staged: StagedWrite,
        active_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        """Move a record out of the active dataset (section 47).

        The archive is staged and validated first, and committed before the
        active file is shortened.  An interruption can therefore only leave the
        record in both places - it can never disappear.
        """

        staged: list[StagedWrite] = [destination_staged]
        try:
            staged.append(self.active.stage_without(item.extension_id, active_rows))
            self.parquet.commit(staged)
        except Exception:
            self.parquet.discard(staged)
            log_event(
                self.logger,
                AuditEvent.PARQUET_WRITE_FAILED,
                level=logging.ERROR,
                extension_id=item.extension_id,
                stage="move",
            )
            raise

    def _latest_actual(
        self, item: ExtensionItem
    ) -> tuple[QVDRecord | None, ComparisonStatus, str | None]:
        """Latest operational record for an extension, with its match state."""

        try:
            matches = self.qvd.load_actual_utilization_data().matches(item.pn, item.sn, item.eo)
        except AmbiguousQVDRecordError:  # pragma: no cover - matches() never raises
            matches = ()
        if not matches:
            return None, ComparisonStatus.NOT_FOUND, "No matching operational record."
        if len(matches) > 1:
            return (
                None,
                ComparisonStatus.NOT_FOUND,
                f"{len(matches)} operational records match this PN / SN / EO.",
            )
        record = matches[0]
        changed = is_after(record.modified_date, item.created_at)
        return (
            record,
            ComparisonStatus.SOURCE_CHANGED if changed else ComparisonStatus.CURRENT,
            None,
        )

    # -- export -------------------------------------------------------------
    def export_application(self, application_id: str) -> Path:
        """Regenerate the business export for an existing application."""

        application = self.get_application(application_id)
        return self.exports.export_application(application)

    # -- construction -------------------------------------------------------
    @classmethod
    def create_default(cls, settings: Settings | None = None) -> "ExtensionService":
        """Wire up the standard Parquet backed service."""

        settings = settings or get_settings()
        settings.ensure_directories()
        return cls(settings)

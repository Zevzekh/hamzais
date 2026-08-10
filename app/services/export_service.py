"""Export mapping (specification sections 26, 27 and 76).

    Internal Extension Model -> Export Mapper -> Required Business Template

The storage schema never depends on the export layout and vice versa.  The
template itself comes from :mod:`app.config.export_config`, so the real
business format can be supplied later as configuration.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.config.export_config import ExportColumn, ExportConfig, build_export_config
from app.config.settings import Settings, get_settings
from app.errors import ExportError
from app.models.extension import ExtensionApplication, ProofDocument
from app.models.extension_item import ExtensionItem
from app.utils.dates import format_date, format_datetime
from app.utils.file_utils import ensure_directory, sanitize_filename
from app.utils.logging_utils import AuditEvent, get_logger, log_event


class ExportService:
    """Turns stored extension rows into the business export file."""

    def __init__(
        self,
        settings: Settings | None = None,
        config: ExportConfig | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config = config or build_export_config()
        self.logger = get_logger("export")

    # --- mapping ---------------------------------------------------------
    def build_export_row(
        self,
        item: ExtensionItem,
        application: ExtensionApplication | None = None,
        documents: Sequence[ProofDocument] = (),
    ) -> dict[str, Any]:
        """Flatten one extension row into the fields a template may use."""

        document_names = [document.original_filename for document in documents]
        return {
            "application_id": item.application_id,
            "extension_id": item.extension_id,
            "extension_type": item.extension_type.value,
            "extension_type_label": item.extension_type.label,
            "pn": item.pn,
            "sn": item.sn,
            "eo": item.eo,
            "current_hours": item.current_hours,
            "current_cycles": item.current_cycles,
            "current_days": item.current_days,
            "current_date": item.current_date,
            "extended_hours": item.extended_hours,
            "extended_cycles": item.extended_cycles,
            "extended_days": item.extended_days,
            "extended_date": item.extended_date,
            "qvd_modified_date_at_application": item.qvd_modified_date_at_application,
            "created_at": item.created_at or (application.created_at if application else None),
            "created_by": item.created_by or (application.created_by if application else ""),
            "status": item.status.value,
            "proof_document_count": len(document_names),
            "proof_document_names": "; ".join(document_names),
            "proof_document_reference": item.proof_document_reference or "",
        }

    def render_value(self, value: Any, column: ExportColumn) -> str:
        if value is None or value == "":
            return self.config.empty_value
        if column.formatter == "date":
            return format_date(value, self.config.date_format, self.config.empty_value)
        if column.formatter == "datetime":
            return format_datetime(value, self.config.datetime_format, self.config.empty_value)
        if column.formatter == "integer":
            return f"{int(round(float(value)))}"
        if column.formatter == "number":
            number = float(value)
            return f"{int(number)}" if number.is_integer() else f"{number}"
        return str(value)

    def map_rows(
        self,
        items: Sequence[ExtensionItem],
        application: ExtensionApplication | None = None,
        documents: Sequence[ProofDocument] = (),
    ) -> list[list[str]]:
        """Apply the template to every row, producing the export grid."""

        rows: list[list[str]] = []
        for item in items:
            source = self.build_export_row(item, application, documents)
            rows.append(
                [self.render_value(source.get(column.field), column) for column in self.config.columns]
            )
        return rows

    @property
    def headers(self) -> list[str]:
        return [column.header for column in self.config.columns]

    # --- writing ---------------------------------------------------------
    def export_application(
        self,
        application: ExtensionApplication,
        items: Sequence[ExtensionItem] | None = None,
        *,
        destination: Path | None = None,
    ) -> Path:
        """Write the export file for one application and return its path."""

        rows = self.map_rows(
            items if items is not None else application.extension_items,
            application,
            application.proof_documents,
        )
        target = destination or self._default_path(application)
        ensure_directory(target.parent)

        try:
            if self.config.file_format == "xlsx":
                self._write_xlsx(target, rows)
            else:
                self._write_csv(target, rows)
        except ExportError:
            raise
        except Exception as exc:
            log_event(
                self.logger,
                AuditEvent.EXPORT_FAILED,
                level=logging.ERROR,
                application_id=application.application_id,
                error=type(exc).__name__,
            )
            raise ExportError(
                f"could not write export file {target}",
                application_id=application.application_id,
            ) from exc

        log_event(
            self.logger,
            AuditEvent.EXPORT_CREATED,
            application_id=application.application_id,
            rows=len(rows),
            file=target.name,
            format=self.config.file_format,
        )
        return target

    def _default_path(self, application: ExtensionApplication) -> Path:
        filename = sanitize_filename(
            self.config.filename(
                application_id=application.application_id,
                extension_type=application.extension_type.value,
            )
        )
        return self.settings.exports_dir / filename

    def _write_csv(self, target: Path, rows: Sequence[Sequence[str]]) -> None:
        with target.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=self.config.delimiter)
            if self.config.include_header:
                writer.writerow(self.headers)
            writer.writerows(rows)

    def _write_xlsx(self, target: Path, rows: Sequence[Sequence[str]]) -> None:
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise ExportError(
                "openpyxl is not installed but the export format is xlsx",
                user_message=(
                    "The configured export format is not available in this installation. "
                    "Please contact the application administrator."
                ),
            ) from exc
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = self.config.sheet_name
        if self.config.include_header:
            sheet.append(self.headers)
        for row in rows:
            sheet.append(list(row))
        workbook.save(target)

    # --- ad hoc exports ---------------------------------------------------
    def export_rows(self, rows: Sequence[Mapping[str, Any]], destination: Path) -> Path:
        """Export an arbitrary table (used by the list screens)."""

        ensure_directory(destination.parent)
        headers = list(rows[0].keys()) if rows else []
        with destination.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=self.config.delimiter)
            if headers:
                writer.writerow(headers)
            for row in rows:
                writer.writerow(["" if row.get(key) is None else row.get(key) for key in headers])
        return destination

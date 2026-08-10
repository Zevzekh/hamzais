"""Export layout configuration (specification sections 26 and 27).

The export template is deliberately separate from the storage schema: the
database must not change shape when the business template changes, and the
template must not change when a column is added to the database.

The exact business format is still to be supplied (section 87), so the layout
below is a placeholder that can be replaced entirely through
``EXTMGMT_EXPORT_TEMPLATE`` (a JSON list of ``{"header", "field",
"formatter"}`` objects) without editing code.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from app.config.settings import ENV_PREFIX
from app.errors import ConfigurationError

#: Supported output formats.
SUPPORTED_FORMATS: tuple[str, ...] = ("csv", "xlsx")

#: Formatter names understood by the export mapper.
FORMATTERS: tuple[str, ...] = ("text", "number", "integer", "date", "datetime", "label")


@dataclass(frozen=True)
class ExportColumn:
    """One column of the business export template."""

    header: str
    field: str
    formatter: str = "text"

    def __post_init__(self) -> None:
        if self.formatter not in FORMATTERS:
            raise ConfigurationError(
                f"unknown export formatter {self.formatter!r} for column {self.header!r}"
            )


@dataclass(frozen=True)
class ExportConfig:
    """Everything the export service needs."""

    columns: Sequence[ExportColumn]
    file_format: str = "csv"
    filename_template: str = "{application_id}_extension_export"
    date_format: str = "%d-%b-%Y"
    datetime_format: str = "%d-%b-%Y %H:%M"
    delimiter: str = ","
    include_header: bool = True
    sheet_name: str = "Extensions"
    empty_value: str = ""
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.file_format not in SUPPORTED_FORMATS:
            raise ConfigurationError(
                f"unsupported export format {self.file_format!r}",
                user_message=(
                    "The configured extension export format is not supported. "
                    "Please contact the application administrator."
                ),
            )

    def filename(self, **context: object) -> str:
        stem = self.filename_template.format(**context)
        return f"{stem}.{self.file_format}"


#: Placeholder business template. Field names refer to the flat export row
#: produced by :mod:`app.services.export_service`.
DEFAULT_EXPORT_COLUMNS: tuple[ExportColumn, ...] = (
    ExportColumn("Application ID", "application_id"),
    ExportColumn("Extension ID", "extension_id"),
    ExportColumn("Extension Type", "extension_type_label", "label"),
    ExportColumn("PN", "pn"),
    ExportColumn("SN", "sn"),
    ExportColumn("EO", "eo"),
    ExportColumn("Current Hours", "current_hours", "number"),
    ExportColumn("Current Cycles", "current_cycles", "number"),
    ExportColumn("Current Days", "current_days", "number"),
    ExportColumn("Current Date", "current_date", "date"),
    ExportColumn("Extended Hours", "extended_hours", "number"),
    ExportColumn("Extended Cycles", "extended_cycles", "number"),
    ExportColumn("Extended Days", "extended_days", "number"),
    ExportColumn("Extended Date", "extended_date", "date"),
    ExportColumn("Application Date", "created_at", "datetime"),
    ExportColumn("Applied By", "created_by"),
    ExportColumn("Proof Documents", "proof_document_names"),
)


def _template_from_env() -> tuple[ExportColumn, ...] | None:
    raw = os.environ.get(f"{ENV_PREFIX}EXPORT_TEMPLATE")
    if not raw:
        return None
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"{ENV_PREFIX}EXPORT_TEMPLATE is not valid JSON",
            user_message=(
                "The extension export template is not configured correctly. "
                "Please contact the application administrator."
            ),
        ) from exc
    if not isinstance(entries, list) or not entries:
        raise ConfigurationError(f"{ENV_PREFIX}EXPORT_TEMPLATE must be a non-empty JSON list")
    columns = []
    for entry in entries:
        if not isinstance(entry, dict) or "field" not in entry:
            raise ConfigurationError(
                f"{ENV_PREFIX}EXPORT_TEMPLATE entries need at least a 'field' key"
            )
        columns.append(
            ExportColumn(
                header=str(entry.get("header") or entry["field"]),
                field=str(entry["field"]),
                formatter=str(entry.get("formatter") or "text"),
            )
        )
    return tuple(columns)


def build_export_config() -> ExportConfig:
    """Build the export configuration from the environment."""

    file_format = (os.environ.get(f"{ENV_PREFIX}EXPORT_FORMAT") or "csv").strip().lower()
    return ExportConfig(
        columns=_template_from_env() or DEFAULT_EXPORT_COLUMNS,
        file_format=file_format,
        filename_template=os.environ.get(
            f"{ENV_PREFIX}EXPORT_FILENAME_TEMPLATE", "{application_id}_extension_export"
        ),
        date_format=os.environ.get(f"{ENV_PREFIX}EXPORT_DATE_FORMAT", "%d-%b-%Y"),
        datetime_format=os.environ.get(
            f"{ENV_PREFIX}EXPORT_DATETIME_FORMAT", "%d-%b-%Y %H:%M"
        ),
        delimiter=os.environ.get(f"{ENV_PREFIX}EXPORT_DELIMITER", ","),
    )

"""Source (QVD) configuration and column mapping.

Section 55: each source declares its own raw column names and the rest of the
system only ever speaks the normalised names ``pn``, ``sn``, ``eo``,
``hours``, ``cycles``, ``days``, ``reference_date`` and ``modified_date``.

Everything here is overridable through environment variables so the exact
production filenames, formats and column names can be supplied later without
touching code (section 87).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

from app.config.settings import ENV_PREFIX, Settings, get_settings
from app.errors import ConfigurationError
from app.models.enums import ExtensionType
from app.utils.normalize import DEFAULT_NULL_TOKENS

#: Logical names of the configured sources.
ENGINEERING_ORDER = "engineering_order"
HARD_TIME_LIMIT = "hard_time_limit"
ACTUAL_UTILIZATION = "actual_utilization"

#: Normalised fields a source may provide.
NORMALIZED_FIELDS: tuple[str, ...] = (
    "pn",
    "sn",
    "eo",
    "hours",
    "cycles",
    "days",
    "reference_date",
    "modified_date",
)

#: Fields that must be resolvable in every source.
REQUIRED_FIELDS: frozenset[str] = frozenset({"pn", "sn", "eo"})

#: Business names used in user facing error messages (section 53).
FIELD_LABELS: Mapping[str, str] = {
    "pn": "Part Number",
    "sn": "Serial Number",
    "eo": "Engineering Order",
    "hours": "Hours",
    "cycles": "Cycles",
    "days": "Days",
    "reference_date": "Reference Date",
    "modified_date": "Modified Date",
}

SOURCE_LABELS: Mapping[str, str] = {
    ENGINEERING_ORDER: "Engineering Order source data",
    HARD_TIME_LIMIT: "Hard Time Limit source data",
    ACTUAL_UTILIZATION: "operational utilisation source data",
}


@dataclass(frozen=True)
class QVDSourceConfig:
    """How to read one source and how to translate its columns."""

    name: str
    path: Path
    reader: str = "csv"
    columns: Mapping[str, str] = field(default_factory=dict)
    optional_fields: frozenset[str] = frozenset({"hours", "cycles", "days", "reference_date", "modified_date"})
    date_formats: tuple[str, ...] = ()
    null_tokens: frozenset[str] = DEFAULT_NULL_TOKENS
    reader_options: Mapping[str, object] = field(default_factory=dict)
    #: Extra raw columns carried through into ``QVDRecord.extra``.
    passthrough_columns: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.name, f"{self.name} source data")

    def source_column(self, normalized_field: str) -> str | None:
        return self.columns.get(normalized_field)

    def is_required(self, normalized_field: str) -> bool:
        return normalized_field in REQUIRED_FIELDS or normalized_field not in self.optional_fields


# --- default column mappings ------------------------------------------------
# Placeholder names, replaced by the real ones through configuration.

ENGINEERING_ORDER_COLUMNS: dict[str, str] = {
    "pn": "PART_NUMBER",
    "sn": "SERIAL_NUMBER",
    "eo": "ENGINEERING_ORDER",
    "hours": "CURRENT_HOURS",
    "cycles": "CURRENT_CYCLES",
    "days": "CURRENT_DAYS",
    "reference_date": "CURRENT_DATE",
    "modified_date": "MODIFIED_DATE",
}

HARD_TIME_LIMIT_COLUMNS: dict[str, str] = {
    "pn": "PART_NUMBER",
    "sn": "SERIAL_NUMBER",
    "eo": "TASK_REFERENCE",
    "hours": "CURRENT_HOURS",
    "cycles": "CURRENT_CYCLES",
    "days": "CURRENT_DAYS",
    "reference_date": "CURRENT_DATE",
    "modified_date": "MODIFIED_DATE",
}

ACTUAL_UTILIZATION_COLUMNS: dict[str, str] = {
    "pn": "PART_NUMBER",
    "sn": "SERIAL_NUMBER",
    "eo": "ENGINEERING_ORDER",
    "hours": "ACTUAL_HOURS",
    "cycles": "ACTUAL_CYCLES",
    "days": "ACTUAL_DAYS",
    "reference_date": "ACTUAL_DATE",
    "modified_date": "MODIFIED_DATE",
}

#: Which source (or sources) an extension type reads from (section 5/6).
EXTENSION_TYPE_SOURCES: Mapping[ExtensionType, str] = {
    ExtensionType.ENGINEERING_ORDER: ENGINEERING_ORDER,
    ExtensionType.HARD_TIME_LIMIT: HARD_TIME_LIMIT,
}


def _env(name: str) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}QVD_{name}")


def _columns_from_env(source: str, defaults: Mapping[str, str]) -> dict[str, str]:
    """Allow ``EXTMGMT_QVD_<SOURCE>_COLUMNS`` as a JSON mapping override."""

    raw = _env(f"{source.upper()}_COLUMNS")
    if not raw:
        return dict(defaults)
    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"{ENV_PREFIX}QVD_{source.upper()}_COLUMNS is not valid JSON",
            user_message=(
                "The source data column mapping is not configured correctly. "
                "Please contact the application administrator."
            ),
        ) from exc
    if not isinstance(overrides, dict):
        raise ConfigurationError(
            f"{ENV_PREFIX}QVD_{source.upper()}_COLUMNS must be a JSON object"
        )
    merged = dict(defaults)
    merged.update({str(k): str(v) for k, v in overrides.items()})
    return merged


def _source_config(
    source: str,
    settings: Settings,
    default_filename: str,
    default_columns: Mapping[str, str],
) -> QVDSourceConfig:
    path_override = _env(f"{source.upper()}_PATH")
    reader = (_env(f"{source.upper()}_READER") or "").strip().lower()
    path = Path(path_override).expanduser() if path_override else settings.qvd_dir / default_filename
    if not reader:
        reader = _reader_for_suffix(path.suffix)
    date_formats_raw = _env(f"{source.upper()}_DATE_FORMATS")
    date_formats = tuple(
        fmt for fmt in (part.strip() for part in (date_formats_raw or "").split("|")) if fmt
    )
    return QVDSourceConfig(
        name=source,
        path=path,
        reader=reader,
        columns=_columns_from_env(source, default_columns),
        date_formats=date_formats,
    )


def _reader_for_suffix(suffix: str) -> str:
    return {
        ".qvd": "qvd",
        ".parquet": "parquet",
        ".pq": "parquet",
        ".csv": "csv",
        ".txt": "csv",
        ".tsv": "csv",
    }.get(suffix.lower(), "csv")


def build_qvd_config(settings: Settings | None = None) -> dict[str, QVDSourceConfig]:
    """Build the source configuration for the given settings."""

    settings = settings or get_settings()
    return {
        ENGINEERING_ORDER: _source_config(
            ENGINEERING_ORDER, settings, "engineering_order.csv", ENGINEERING_ORDER_COLUMNS
        ),
        HARD_TIME_LIMIT: _source_config(
            HARD_TIME_LIMIT, settings, "hard_time_limit.csv", HARD_TIME_LIMIT_COLUMNS
        ),
        ACTUAL_UTILIZATION: _source_config(
            ACTUAL_UTILIZATION, settings, "actual_utilization.csv", ACTUAL_UTILIZATION_COLUMNS
        ),
    }


def source_for_extension_type(extension_type: ExtensionType) -> str:
    try:
        return EXTENSION_TYPE_SOURCES[extension_type]
    except KeyError as exc:  # pragma: no cover - guarded by the enum
        raise ConfigurationError(
            f"no source configured for extension type {extension_type}",
        ) from exc


def with_path(config: QVDSourceConfig, path: Path, reader: str | None = None) -> QVDSourceConfig:
    """Return a copy of ``config`` pointed at a different file (used in tests)."""

    return replace(config, path=Path(path), reader=reader or _reader_for_suffix(Path(path).suffix))

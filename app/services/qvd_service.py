"""The only door to source (QVD) data.

The UI never reads a source file and never sees a raw column name
(specification sections 6, 55 and 85.4).  This service reads, translates,
normalises, caches and indexes each configured source and hands out
:class:`~app.models.qvd_record.QVDRecord` objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.config.qvd_config import (
    ACTUAL_UTILIZATION,
    ENGINEERING_ORDER,
    FIELD_LABELS,
    HARD_TIME_LIMIT,
    NORMALIZED_FIELDS,
    QVDSourceConfig,
    build_qvd_config,
    source_for_extension_type,
)
from app.config.settings import Settings, get_settings
from app.errors import (
    AmbiguousQVDRecordError,
    ConfigurationError,
    QVDColumnMappingError,
)
from app.models.enums import ExtensionType
from app.models.qvd_record import LookupKey, QVDRecord
from app.utils.dates import parse_optional_datetime, to_utc_datetime, ensure_utc
from app.utils.logging_utils import AuditEvent, get_logger, log_event
from app.utils.normalize import make_lookup_key, normalize_key, normalize_number

_DATE_FIELDS = frozenset({"reference_date", "modified_date"})
_NUMERIC_FIELDS = frozenset({"hours", "cycles", "days"})


@dataclass(frozen=True)
class QVDDataset:
    """A loaded, normalised and indexed source.

    Section 64: lookups hit a dictionary, they never scan the whole dataset.
    """

    name: str
    records: tuple[QVDRecord, ...]
    index: Mapping[LookupKey, tuple[QVDRecord, ...]]
    loaded_at: datetime
    source_path: Path
    fingerprint: tuple[int, int] | None
    latest_modified_date: datetime | None

    def __len__(self) -> int:
        return len(self.records)

    def lookup(self, pn: Any, sn: Any, eo: Any) -> QVDRecord | None:
        """Find one record, refusing to guess when the source is ambiguous."""

        key = make_lookup_key(pn, sn, eo)
        matches = self.index.get(key, ())
        if not matches:
            return None
        if len(matches) > 1:
            raise AmbiguousQVDRecordError(
                f"{len(matches)} source records match {key} in {self.name}",
                source=self.name,
                pn=key[0],
                sn=key[1],
                eo=key[2],
                matches=len(matches),
            )
        return matches[0]

    def matches(self, pn: Any, sn: Any, eo: Any) -> tuple[QVDRecord, ...]:
        return self.index.get(make_lookup_key(pn, sn, eo), ())


class QVDService:
    """Loads, normalises and caches the configured sources."""

    def __init__(
        self,
        settings: Settings | None = None,
        configs: Mapping[str, QVDSourceConfig] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.configs: dict[str, QVDSourceConfig] = dict(
            configs if configs is not None else build_qvd_config(self.settings)
        )
        self.logger = get_logger("qvd")
        self._cache: dict[str, QVDDataset] = {}

    # --- configuration ---------------------------------------------------
    def config_for(self, source_name: str) -> QVDSourceConfig:
        try:
            return self.configs[source_name]
        except KeyError as exc:
            raise ConfigurationError(
                f"unknown source {source_name!r}", source=source_name
            ) from exc

    def set_config(self, config: QVDSourceConfig) -> None:
        """Point a source somewhere else (used by tests and admin tooling)."""

        self.configs[config.name] = config
        self._cache.pop(config.name, None)

    # --- loading ---------------------------------------------------------
    def load(self, source_name: str, *, force_reload: bool = False) -> QVDDataset:
        """Return the cached dataset, reloading when the file changed.

        Section 63: the cache must never serve stale operational data
        indefinitely, so the file fingerprint is checked on every call.
        """

        config = self.config_for(source_name)
        cached = self._cache.get(source_name)
        fingerprint = self._fingerprint(config.path)
        if cached is not None and not force_reload and cached.fingerprint == fingerprint:
            return cached

        dataset = self._load_dataset(config, fingerprint)
        self._cache[source_name] = dataset
        log_event(
            self.logger,
            AuditEvent.QVD_LOAD,
            source=source_name,
            rows=len(dataset),
            file=Path(config.path).name,
            reloaded=cached is not None,
        )
        return dataset

    def load_engineering_order_data(self, *, force_reload: bool = False) -> QVDDataset:
        return self.load(ENGINEERING_ORDER, force_reload=force_reload)

    def load_hard_time_limit_data(self, *, force_reload: bool = False) -> QVDDataset:
        return self.load(HARD_TIME_LIMIT, force_reload=force_reload)

    def load_actual_utilization_data(self, *, force_reload: bool = False) -> QVDDataset:
        return self.load(ACTUAL_UTILIZATION, force_reload=force_reload)

    def load_for_extension_type(
        self, extension_type: ExtensionType, *, force_reload: bool = False
    ) -> QVDDataset:
        return self.load(source_for_extension_type(extension_type), force_reload=force_reload)

    def refresh(self, source_name: str | None = None) -> None:
        """Drop cached data so the next call re-reads the source (section 68)."""

        if source_name is None:
            self._cache.clear()
        else:
            self._cache.pop(source_name, None)
        log_event(self.logger, AuditEvent.QVD_REFRESH, source=source_name or "all")

    # --- lookups ---------------------------------------------------------
    def lookup_extension_record(
        self,
        extension_type: ExtensionType,
        pn: Any,
        sn: Any,
        eo: Any,
    ) -> QVDRecord | None:
        """Find the source record backing one extension row (section 12)."""

        source_name = source_for_extension_type(extension_type)
        dataset = self.load(source_name)
        record = dataset.lookup(pn, sn, eo)
        log_event(
            self.logger,
            AuditEvent.QVD_LOOKUP,
            source=source_name,
            pn=normalize_key(pn),
            sn=normalize_key(sn),
            eo=normalize_key(eo),
            found=record is not None,
        )
        return record

    def lookup_actual_record(self, pn: Any, sn: Any, eo: Any) -> QVDRecord | None:
        """Latest operational utilisation for one PN/SN/EO (section 29)."""

        return self.load_actual_utilization_data().lookup(pn, sn, eo)

    def actual_records_by_key(
        self, *, force_reload: bool = False
    ) -> Mapping[LookupKey, tuple[QVDRecord, ...]]:
        """Whole operational index, for joining many extensions at once."""

        return self.load_actual_utilization_data(force_reload=force_reload).index

    # --- internals -------------------------------------------------------
    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, int] | None:
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _load_dataset(
        self, config: QVDSourceConfig, fingerprint: tuple[int, int] | None
    ) -> QVDDataset:
        from app.services.qvd_readers import get_reader

        raw = get_reader(config.reader)(config)
        self._check_columns(config, raw.columns)

        file_modified = self._file_modified(config.path)
        records: list[QVDRecord] = []
        for position, row in enumerate(raw.rows, start=1):
            record = self._to_record(config, row, position, file_modified)
            if record is not None:
                records.append(record)

        index: dict[LookupKey, list[QVDRecord]] = {}
        for record in records:
            index.setdefault(record.key, []).append(record)

        modified_dates = [r.modified_date for r in records if r.modified_date is not None]
        return QVDDataset(
            name=config.name,
            records=tuple(records),
            index={key: tuple(value) for key, value in index.items()},
            loaded_at=ensure_utc(datetime.now()),
            source_path=Path(config.path),
            fingerprint=fingerprint,
            latest_modified_date=max(modified_dates) if modified_dates else file_modified,
        )

    def _check_columns(self, config: QVDSourceConfig, columns: Sequence[str]) -> None:
        """Fail early, and in business language, on a mapping mismatch."""

        available = {str(column).strip() for column in columns}
        if not available:
            return  # empty source file - nothing to verify
        for field_name in NORMALIZED_FIELDS:
            source_column = config.source_column(field_name)
            if source_column is None:
                if config.is_required(field_name):
                    raise QVDColumnMappingError(
                        f"no column mapping configured for {field_name!r} in {config.name}",
                        user_message=(
                            f"The required {FIELD_LABELS.get(field_name, field_name)} field "
                            f"is not configured for the {config.label}. "
                            "Please contact the application administrator."
                        ),
                        source=config.name,
                        field=field_name,
                    )
                continue
            if source_column not in available and config.is_required(field_name):
                raise QVDColumnMappingError(
                    f"column {source_column!r} missing from {config.path}",
                    user_message=(
                        f"The required {FIELD_LABELS.get(field_name, field_name)} field "
                        f"could not be found in the {config.label}. "
                        "Please contact the application administrator."
                    ),
                    source=config.name,
                    field=field_name,
                    column=source_column,
                )

    def _to_record(
        self,
        config: QVDSourceConfig,
        row: Mapping[str, Any],
        position: int,
        file_modified: datetime | None,
    ) -> QVDRecord | None:
        values: dict[str, Any] = {}
        for field_name in NORMALIZED_FIELDS:
            source_column = config.source_column(field_name)
            raw_value = row.get(source_column) if source_column else None
            if field_name in _DATE_FIELDS:
                values[field_name] = self._parse_date(config, raw_value, field_name, position)
            elif field_name in _NUMERIC_FIELDS:
                values[field_name] = self._parse_number(config, raw_value, field_name, position)
            else:
                values[field_name] = normalize_key(raw_value, config.null_tokens)

        if values["pn"] is None and values["sn"] is None and values["eo"] is None:
            return None  # blank line in the source

        modified = values["modified_date"] or file_modified
        extra = {column: row.get(column) for column in config.passthrough_columns if column in row}
        return QVDRecord(
            pn=values["pn"],
            sn=values["sn"],
            eo=values["eo"],
            hours=values["hours"],
            cycles=values["cycles"],
            days=values["days"],
            reference_date=values["reference_date"],
            modified_date=modified,
            source=config.name,
            row_number=position,
            extra=extra,
        )

    def _parse_date(
        self, config: QVDSourceConfig, value: Any, field_name: str, position: int
    ) -> datetime | None:
        try:
            return to_utc_datetime(value, config.date_formats, null_tokens=config.null_tokens)
        except ValueError:
            self.logger.warning(
                "source %s row %s: %s value %r is not a recognisable date; treated as missing",
                config.name,
                position,
                field_name,
                value,
            )
            return None

    def _parse_number(
        self, config: QVDSourceConfig, value: Any, field_name: str, position: int
    ) -> float | int | None:
        try:
            return normalize_number(value, null_tokens=config.null_tokens)
        except ValueError:
            self.logger.warning(
                "source %s row %s: %s value %r is not numeric; treated as missing",
                config.name,
                position,
                field_name,
                value,
            )
            return None

    @staticmethod
    def _file_modified(path: Path) -> datetime | None:
        """Fallback modification date for sources without a modified column."""

        try:
            return parse_optional_datetime(
                datetime.fromtimestamp(Path(path).stat().st_mtime)
            )
        except OSError:
            return None

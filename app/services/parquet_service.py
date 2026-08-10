"""Low level Parquet input/output.

This is the only module in the application allowed to touch Parquet files.
It implements the safety requirements of the specification:

* section 24 - never overwrite the only copy: write a temporary file, read it
  back, and only then replace the original;
* section 25 - all mutations happen under a cross process write lock;
* section 47 - a move between datasets stages every file first and commits in
  an order that can never lose the source record;
* section 81 - a rolling backup is taken before a file is replaced.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from app.config.settings import Settings, get_settings
from app.errors import StorageError
from app.utils.dates import ensure_utc, timestamp_slug, to_utc_datetime
from app.utils.locking import write_lock
from app.utils.logging_utils import AuditEvent, get_logger, log_event

TMP_SUFFIX = ".tmp.parquet"


def _coerce(value: Any, arrow_type: pa.DataType) -> Any:
    """Convert a Python value into something Arrow accepts for ``arrow_type``."""

    if value is None:
        return None
    if pa.types.is_timestamp(arrow_type):
        parsed = to_utc_datetime(value)
        return ensure_utc(parsed) if parsed else None
    if pa.types.is_floating(arrow_type):
        return float(value)
    if pa.types.is_integer(arrow_type):
        return int(value)
    if pa.types.is_string(arrow_type):
        return value if isinstance(value, str) else str(value)
    return value  # pragma: no cover - no other types in use


def records_to_table(records: Sequence[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    """Build an Arrow table from plain dictionaries.

    Columns are built one by one against the declared type, which avoids the
    dtype guessing that would otherwise turn an all-``None`` column into
    something the schema rejects.
    """

    columns = {}
    for field in schema:
        values = [_coerce(record.get(field.name), field.type) for record in records]
        try:
            columns[field.name] = pa.array(values, type=field.type)
        except (pa.ArrowInvalid, pa.ArrowTypeError, ValueError, TypeError) as exc:
            raise StorageError(
                f"column {field.name!r} contains a value that does not fit {field.type}",
                column=field.name,
            ) from exc
    return pa.Table.from_pydict(columns, schema=schema)


def table_to_records(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist()


@dataclass(frozen=True)
class StagedWrite:
    """A validated temporary file waiting to replace its target."""

    target: Path
    temp_path: Path
    row_count: int

    def discard(self) -> None:
        with contextlib.suppress(OSError):
            self.temp_path.unlink()


class ParquetService:
    """Safe reads, staged writes and multi-file commits."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("parquet")

    # --- locking ---------------------------------------------------------
    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Hold the global write lock for a whole read-modify-write cycle."""

        with write_lock(self.settings.lock_file, self.settings.lock_timeout_seconds):
            yield

    # --- reading ---------------------------------------------------------
    def read_table(self, path: Path, schema: pa.Schema) -> pa.Table:
        path = Path(path)
        if not path.exists():
            return schema.empty_table()
        try:
            table = pq.read_table(path)
        except Exception as exc:
            log_event(
                self.logger,
                AuditEvent.PARQUET_WRITE_FAILED,
                level=logging.ERROR,
                file=path.name,
                error=type(exc).__name__,
            )
            raise StorageError(
                f"could not read Parquet file {path}",
                user_message=(
                    "The extension database could not be read. "
                    "Please contact the application administrator."
                ),
                file=str(path),
            ) from exc
        return self._align(table, schema)

    def read_records(self, path: Path, schema: pa.Schema) -> list[dict[str, Any]]:
        return table_to_records(self.read_table(path, schema))

    @staticmethod
    def _align(table: pa.Table, schema: pa.Schema) -> pa.Table:
        """Reconcile a stored file with the current schema.

        Missing columns are added as nulls so a schema addition does not make
        existing data unreadable; unknown columns are dropped.
        """

        if table.schema.equals(schema):
            return table
        columns: dict[str, Any] = {}
        for field in schema:
            if field.name in table.column_names:
                column = table.column(field.name)
                if not column.type.equals(field.type):
                    column = column.cast(field.type)
                columns[field.name] = column
            else:
                columns[field.name] = pa.chunked_array(
                    [pa.nulls(table.num_rows, type=field.type)], type=field.type
                )
        return pa.Table.from_pydict(columns, schema=schema)

    # --- writing ---------------------------------------------------------
    def stage(
        self,
        path: Path,
        records: Sequence[dict[str, Any]],
        schema: pa.Schema,
    ) -> StagedWrite:
        """Write and validate a temporary file next to ``path``.

        The original file is untouched until :meth:`commit` runs.
        """

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(path.stem + TMP_SUFFIX)
        with contextlib.suppress(OSError):
            temp_path.unlink()

        try:
            table = records_to_table(records, schema)
            pq.write_table(table, temp_path)
        except StorageError:
            raise
        except Exception as exc:
            log_event(
                self.logger,
                AuditEvent.PARQUET_WRITE_FAILED,
                level=logging.ERROR,
                file=path.name,
                stage="write_temp",
                error=type(exc).__name__,
            )
            raise StorageError(f"could not write temporary file for {path}", file=str(path)) from exc

        self._validate_temp(temp_path, path, schema, len(records))
        return StagedWrite(target=path, temp_path=temp_path, row_count=len(records))

    def _validate_temp(
        self, temp_path: Path, target: Path, schema: pa.Schema, expected_rows: int
    ) -> None:
        """Read the temporary file back before it is allowed to replace anything."""

        try:
            written = pq.read_table(temp_path)
        except Exception as exc:
            with contextlib.suppress(OSError):
                temp_path.unlink()
            log_event(
                self.logger,
                AuditEvent.PARQUET_WRITE_FAILED,
                level=logging.ERROR,
                file=target.name,
                stage="validate_temp",
                error=type(exc).__name__,
            )
            raise StorageError(f"temporary file for {target} is not readable", file=str(target)) from exc

        if written.num_rows != expected_rows or not written.schema.equals(schema):
            with contextlib.suppress(OSError):
                temp_path.unlink()
            log_event(
                self.logger,
                AuditEvent.PARQUET_WRITE_FAILED,
                level=logging.ERROR,
                file=target.name,
                stage="validate_temp",
                expected_rows=expected_rows,
                actual_rows=written.num_rows,
            )
            raise StorageError(
                f"temporary file for {target} did not validate",
                file=str(target),
                expected_rows=expected_rows,
                actual_rows=written.num_rows,
            )

    def commit(self, staged: Sequence[StagedWrite]) -> None:
        """Replace targets with their validated temporary files.

        Callers order ``staged`` so the destination of a move is committed
        before the source is shortened (section 47): an interruption can then
        only ever duplicate a record, never lose it.
        """

        for item in staged:
            self._backup(item.target)

        replaced: list[StagedWrite] = []
        try:
            for item in staged:
                os.replace(item.temp_path, item.target)
                replaced.append(item)
                log_event(
                    self.logger,
                    AuditEvent.PARQUET_WRITE,
                    file=item.target.name,
                    rows=item.row_count,
                )
        except OSError as exc:
            for item in staged:
                if item not in replaced:
                    item.discard()
            log_event(
                self.logger,
                AuditEvent.PARQUET_WRITE_FAILED,
                level=logging.ERROR,
                stage="commit",
                committed=len(replaced),
                total=len(staged),
                error=type(exc).__name__,
            )
            raise StorageError(
                "the extension database could not be updated during commit",
                committed=len(replaced),
                total=len(staged),
            ) from exc

    def discard(self, staged: Iterable[StagedWrite]) -> None:
        for item in staged:
            item.discard()

    def write(
        self, path: Path, records: Sequence[dict[str, Any]], schema: pa.Schema
    ) -> None:
        """Stage and commit a single file."""

        self.commit([self.stage(path, records, schema)])

    # --- backups ---------------------------------------------------------
    def _backup(self, path: Path) -> None:
        if not self.settings.backup_enabled or not path.exists():
            return
        try:
            self.settings.backup_dir.mkdir(parents=True, exist_ok=True)
            destination = self.settings.backup_dir / f"{path.stem}_{timestamp_slug()}{path.suffix}"
            counter = 1
            while destination.exists():
                destination = destination.with_name(
                    f"{path.stem}_{timestamp_slug()}_{counter}{path.suffix}"
                )
                counter += 1
            shutil.copy2(path, destination)
            log_event(self.logger, AuditEvent.PARQUET_BACKUP, file=path.name, backup=destination.name)
            self._prune_backups(path.stem, path.suffix)
        except OSError as exc:  # a failed backup must not block the business action
            self.logger.warning("backup of %s failed: %s", path, exc)

    def _prune_backups(self, stem: str, suffix: str) -> None:
        retention = max(0, self.settings.backup_retention)
        if retention == 0:
            return
        backups = sorted(
            self.settings.backup_dir.glob(f"{stem}_*{suffix}"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for stale in backups[retention:]:
            with contextlib.suppress(OSError):
                stale.unlink()

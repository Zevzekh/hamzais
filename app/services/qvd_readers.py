"""Readers that turn a configured source file into raw rows.

Keeping the file format behind a small registry means the production ``.qvd``
adapter can be dropped in later without touching the service, the UI or the
tests (specification sections 6 and 87).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.config.qvd_config import QVDSourceConfig
from app.errors import QVDReaderNotAvailableError, QVDSourceUnavailableError


@dataclass(frozen=True)
class RawTable:
    """Untranslated source rows plus the column names that were present."""

    columns: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self.rows)


Reader = Callable[[QVDSourceConfig], RawTable]

_READERS: dict[str, Reader] = {}


def register_reader(name: str, reader: Reader) -> None:
    """Register a source reader under a logical format name."""

    _READERS[name.strip().lower()] = reader


def get_reader(name: str) -> Reader:
    try:
        return _READERS[name.strip().lower()]
    except KeyError as exc:
        raise QVDReaderNotAvailableError(
            f"no reader registered for source format {name!r}",
            reader=name,
        ) from exc


def available_readers() -> tuple[str, ...]:
    return tuple(sorted(_READERS))


def _require_file(config: QVDSourceConfig) -> Path:
    path = Path(config.path)
    if not path.exists():
        raise QVDSourceUnavailableError(
            f"source file {path} does not exist",
            user_message=(
                f"The {config.label} is currently unavailable. "
                "Please contact the application administrator."
            ),
            source=config.name,
            path=str(path),
        )
    return path


def read_csv(config: QVDSourceConfig) -> RawTable:
    """Delimited text. Values stay as text so null handling stays in one place."""

    import pandas as pd

    path = _require_file(config)
    options: dict[str, Any] = {
        "dtype": str,
        "keep_default_na": False,
        "na_filter": False,
        "encoding": "utf-8-sig",
    }
    options.update(config.reader_options)
    try:
        frame = pd.read_csv(path, **options)
    except Exception as exc:
        raise QVDSourceUnavailableError(
            f"could not parse {path}",
            user_message=(
                f"The {config.label} could not be read. "
                "Please contact the application administrator."
            ),
            source=config.name,
            path=str(path),
        ) from exc
    columns = tuple(str(column) for column in frame.columns)
    return RawTable(columns=columns, rows=tuple(frame.to_dict(orient="records")))


def read_parquet(config: QVDSourceConfig) -> RawTable:
    import pyarrow.parquet as pq

    path = _require_file(config)
    try:
        table = pq.read_table(path)
    except Exception as exc:
        raise QVDSourceUnavailableError(
            f"could not read {path}",
            user_message=(
                f"The {config.label} could not be read. "
                "Please contact the application administrator."
            ),
            source=config.name,
            path=str(path),
        ) from exc
    return RawTable(columns=tuple(table.column_names), rows=tuple(table.to_pylist()))


def read_qvd(config: QVDSourceConfig) -> RawTable:
    """Native Qlik QVD.

    Delegates to whichever QVD library the deployment has installed.  When
    none is available the error explains the situation in business terms
    rather than surfacing an ImportError.
    """

    path = _require_file(config)

    try:  # PyQvd >= 1.0
        from pyqvd import QvdTable  # type: ignore

        table = QvdTable.from_qvd(str(path))
        columns = tuple(str(column) for column in table.columns)
        rows = tuple(dict(zip(columns, row)) for row in table.to_dict()["data"])
        return RawTable(columns=columns, rows=rows)
    except ImportError:
        pass
    except Exception as exc:
        raise QVDSourceUnavailableError(
            f"could not read {path}",
            user_message=(
                f"The {config.label} could not be read. "
                "Please contact the application administrator."
            ),
            source=config.name,
            path=str(path),
        ) from exc

    try:  # qvd / qvd-reader style API
        from qvd import qvd_reader  # type: ignore

        frame = qvd_reader.read(str(path))
        columns = tuple(str(column) for column in frame.columns)
        return RawTable(columns=columns, rows=tuple(frame.to_dict(orient="records")))
    except ImportError as exc:
        raise QVDReaderNotAvailableError(
            "no QVD reader library is installed in this environment",
            source=config.name,
            path=str(path),
        ) from exc
    except Exception as exc:
        raise QVDSourceUnavailableError(
            f"could not read {path}",
            user_message=(
                f"The {config.label} could not be read. "
                "Please contact the application administrator."
            ),
            source=config.name,
            path=str(path),
        ) from exc


def read_memory(config: QVDSourceConfig) -> RawTable:
    """In-memory rows supplied through ``reader_options['records']``.

    Used by tests and demos so no production source is ever required
    (specification section 73).
    """

    records: Sequence[Mapping[str, Any]] = config.reader_options.get("records", ())  # type: ignore[assignment]
    rows = tuple(dict(record) for record in records)
    columns = tuple(config.reader_options.get("columns") or (rows[0].keys() if rows else ()))
    return RawTable(columns=tuple(str(column) for column in columns), rows=rows)


register_reader("csv", read_csv)
register_reader("parquet", read_parquet)
register_reader("qvd", read_qvd)
register_reader("memory", read_memory)

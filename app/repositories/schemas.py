"""Parquet schemas for the three extension datasets and the document dataset.

Notes on types (specification sections 56 and 57):

* Every datetime column is a timezone aware UTC timestamp. Business dates are
  never stored as formatted strings.
* Hours, cycles and days are stored as ``float64``.  That keeps ``NULL``
  distinct from ``0`` and does not force fractional source values into
  integers; the display and export layers render whole numbers without a
  decimal part.
"""

from __future__ import annotations

import pyarrow as pa

from app.models.archive import COMPLETED_FIELDS, DELETED_FIELDS
from app.models.extension import DOCUMENT_FIELDS
from app.models.extension_item import ITEM_FIELDS

TIMESTAMP = pa.timestamp("us", tz="UTC")
NUMBER = pa.float64()
TEXT = pa.string()

#: Type of every known column, by name.
COLUMN_TYPES: dict[str, pa.DataType] = {
    "application_id": TEXT,
    "extension_id": TEXT,
    "extension_type": TEXT,
    "pn": TEXT,
    "sn": TEXT,
    "eo": TEXT,
    "current_hours": NUMBER,
    "current_cycles": NUMBER,
    "current_days": NUMBER,
    "current_date": TIMESTAMP,
    "extended_hours": NUMBER,
    "extended_cycles": NUMBER,
    "extended_days": NUMBER,
    "extended_date": TIMESTAMP,
    "qvd_modified_date_at_application": TIMESTAMP,
    "created_at": TIMESTAMP,
    "created_by": TEXT,
    "proof_document_reference": TEXT,
    "status": TEXT,
    # completed archive
    "actual_hours_at_completion": NUMBER,
    "actual_cycles_at_completion": NUMBER,
    "actual_days_at_completion": NUMBER,
    "qvd_modified_date_at_completion": TIMESTAMP,
    "completion_date": TIMESTAMP,
    "completed_by": TEXT,
    "completion_source_status": TEXT,
    # deleted archive
    "deleted_at": TIMESTAMP,
    "deleted_by": TEXT,
    "deletion_reason": TEXT,
    # documents
    "document_id": TEXT,
    "original_filename": TEXT,
    "stored_filename": TEXT,
    "relative_path": TEXT,
    "size_bytes": pa.int64(),
    "content_type": TEXT,
    "uploaded_at": TIMESTAMP,
    "uploaded_by": TEXT,
}


def build_schema(field_names: tuple[str, ...]) -> pa.Schema:
    missing = [name for name in field_names if name not in COLUMN_TYPES]
    if missing:  # pragma: no cover - developer error
        raise KeyError(f"no Parquet type declared for columns: {missing}")
    return pa.schema([pa.field(name, COLUMN_TYPES[name]) for name in field_names])


ACTIVE_SCHEMA: pa.Schema = build_schema(ITEM_FIELDS)
COMPLETED_SCHEMA: pa.Schema = build_schema(COMPLETED_FIELDS)
DELETED_SCHEMA: pa.Schema = build_schema(DELETED_FIELDS)
DOCUMENT_SCHEMA: pa.Schema = build_schema(DOCUMENT_FIELDS)

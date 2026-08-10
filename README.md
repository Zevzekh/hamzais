# Extension Management

An internal business application for managing technical extensions: applying
for them, reviewing them against the latest operational data, and closing them
out.

## What it does

| Workflow | What happens |
| --- | --- |
| **Create New Extension** | Choose Engineering Order or Hard Time Limits, attach supporting documents, add one or many extension rows. Current hours/cycles/days are read automatically from the source data and frozen; the user enters the extended limits. On submission the rows are stored and a business export file is generated. |
| **Show Applied Extensions** | Every active extension joined, in memory, with the latest operational data: actual hours, cycles and days, plus a review state of `CURRENT`, `SOURCE_CHANGED` or `NOT_FOUND`. |
| **Modify Extensions** | Complete an extension — archived together with the utilisation recorded at completion — or delete it. Both are confirmed explicitly, and neither discards history. |

## Getting started

```bash
pip install -r requirements.txt

# Create sample source data so the application can run without production files
python scripts/seed_sample_data.py

# Check the resolved configuration and where the data lives
python main.py --check

# Start the user interface
streamlit run main.py
```

Run the tests with `python -m pytest tests`.

## How it is put together

```
UI  ──►  ExtensionService  ──┬──►  QVDService        ──►  source files
                             ├──►  ValidationService
                             ├──►  DocumentService
                             ├──►  ExportService
                             └──►  Repositories      ──►  Parquet databases
```

```
app/
├── ui/            Streamlit screens and their components. No file access.
├── services/      Business orchestration, source data, validation, export.
├── repositories/  One class per stored dataset. The only Parquet callers.
├── models/        Domain objects, drafts and view models.
├── config/        Settings, source column mappings, export template.
└── utils/         Dates, identifiers, normalisation, locking, logging.
```

Three rules hold the design together:

1. **The UI never touches a file.** No screen reads a source file or calls
   `read_parquet`. Everything goes through a service.
2. **Historical values are frozen.** The current values captured when an
   extension is created never change, even when the source data moves on. A
   later change raises a warning; it never rewrites a record.
3. **Nothing is deleted.** Completing or deleting an extension moves it to an
   archive that preserves the original record and adds the provenance of the
   event.

### Data flow

```
CREATE ──► ACTIVE ──┬──► COMPLETE ──► completed_extensions.parquet
                    └──► DELETE   ──► deleted_extensions.parquet
```

| File | Contents |
| --- | --- |
| `data/active/extensions.parquet` | Extensions currently in force. One row per extension item. |
| `data/completed/completed_extensions.parquet` | Completed extensions plus the utilisation at completion. |
| `data/deleted/deleted_extensions.parquet` | Deleted extensions plus who deleted them, when and why. |
| `data/documents.parquet` | Supporting document metadata. |
| `data/documents/<application_id>/` | The document files themselves. |
| `data/exports/` | Generated business export files. |
| `data/backup/` | Rolling backups taken before each database replacement. |

### Identifiers

One submission is an **application**; each row within it is an **extension**:

```
application_id  EXT-2026-000001
extension_id    EXT-2026-000001-001
                EXT-2026-000001-002
```

Both are immutable and are never reused, including after archiving. Delete and
Complete always act on an `extension_id` — never on a row position.

### Storage safety

Parquet is being used as a business database, so writes are defensive:

- every write goes to a temporary file which is read back and validated before
  it replaces the original;
- a rolling backup is taken before each replacement;
- all mutations run under a cross-process write lock, so two users cannot load
  the same snapshot and overwrite each other;
- moving a record between datasets writes the **archive first**. If anything
  fails, the active record is still there — an interruption can duplicate a
  record, never lose one.

## Configuration

Nothing is hard-coded. Every path, policy and mapping is an environment
variable prefixed with `EXTMGMT_`; see `app/config/settings.py`,
`app/config/qvd_config.py` and `app/config/export_config.py`.

| Variable | Purpose | Default |
| --- | --- | --- |
| `EXTMGMT_DATA_DIR` | Root of the databases, documents and exports | `./data` |
| `EXTMGMT_QVD_ENGINEERING_ORDER_PATH` | Engineering Order source file | `data/qvd/engineering_order.csv` |
| `EXTMGMT_QVD_HARD_TIME_LIMIT_PATH` | Hard Time Limit source file | `data/qvd/hard_time_limit.csv` |
| `EXTMGMT_QVD_ACTUAL_UTILIZATION_PATH` | Operational utilisation source file | `data/qvd/actual_utilization.csv` |
| `EXTMGMT_QVD_<SOURCE>_COLUMNS` | JSON mapping of internal field → source column | see `qvd_config.py` |
| `EXTMGMT_QVD_<SOURCE>_READER` | `csv`, `parquet` or `qvd` | inferred from the file extension |
| `EXTMGMT_EXPORT_TEMPLATE` | JSON list of `{header, field, formatter}` | placeholder layout |
| `EXTMGMT_EXPORT_FORMAT` | `csv` or `xlsx` | `csv` |
| `EXTMGMT_DUPLICATE_POLICY` | `BLOCK`, `WARN` or `ALLOW` | `BLOCK` |
| `EXTMGMT_REQUIRE_PROOF_DOCUMENTS` | Whether supporting documents are mandatory | `true` |
| `EXTMGMT_LIMIT_MONITORING_ENABLED` | Calculate approaching/exceeded limit states | `false` |

### Connecting the real source data

The source layer reads CSV and Parquet out of the box. Native `.qvd` files are
read through whichever QVD library the deployment installs; if none is
present, the user is told the format cannot be read here rather than seeing an
import error. To point the application at real sources:

1. set the three `_PATH` variables;
2. set the matching `_COLUMNS` mappings to the real column names;
3. set `_READER` if the extension does not imply the format.

No application code changes.

### Still to be parameterised

These are configuration or interfaces today and can be filled in when the
business supplies them: the exact source filenames and column names, the
business export template and file type, the accepted proof-document types,
the extended-value validation rules, the duplicate policy, and the
authentication source (the current user is captured in the sidebar).

## Testing

```
tests/
├── unit/         Normalisation, dates, identifiers, source lookup,
│                 validation, repositories, documents, export, view models.
├── integration/  The six end-to-end workflows plus concurrent writers.
└── fixtures/     Deterministic mock source data.
```

Tests never read production source data and never write outside a temporary
directory. The integration suite covers create, the source-changed warning,
the current state, complete, delete, and a simulated failure during archiving
that must leave the active record intact.

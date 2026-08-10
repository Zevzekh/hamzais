"""Shared test fixtures.

Every test runs against a settings object rooted at a temporary directory, so
no production path, source file or database is ever touched.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.qvd_config import (  # noqa: E402
    ACTUAL_UTILIZATION,
    ENGINEERING_ORDER,
    HARD_TIME_LIMIT,
    build_qvd_config,
)
from app.config.settings import Settings, reset_settings, set_settings  # noqa: E402
from app.models.drafts import (  # noqa: E402
    ExtensionApplicationDraft,
    ExtensionRowDraft,
    PendingDocument,
)
from app.models.enums import ExtensionType  # noqa: E402
from app.services.extension_service import ExtensionService  # noqa: E402
from app.services.qvd_service import QVDService  # noqa: E402
from tests.fixtures import qvd_data  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings rooted in a temporary directory, active for the whole test."""

    configured = Settings.for_root(tmp_path, backup_retention=3)
    configured.ensure_directories()
    set_settings(configured)
    yield configured
    reset_settings()


@pytest.fixture
def source_files(settings: Settings) -> dict[str, Path]:
    """Write the standard mock sources into the temporary source folder."""

    configs = build_qvd_config(settings)
    paths = {
        ENGINEERING_ORDER: qvd_data.write_engineering_order(
            Path(configs[ENGINEERING_ORDER].path)
        ),
        HARD_TIME_LIMIT: qvd_data.write_hard_time_limit(Path(configs[HARD_TIME_LIMIT].path)),
        ACTUAL_UTILIZATION: qvd_data.write_actual_utilization(
            Path(configs[ACTUAL_UTILIZATION].path)
        ),
    }
    return paths


@pytest.fixture
def write_source(settings: Settings):
    """Rewrite one source file with bespoke rows mid-test."""

    configs = build_qvd_config(settings)
    writers = {
        ENGINEERING_ORDER: qvd_data.write_engineering_order,
        HARD_TIME_LIMIT: qvd_data.write_hard_time_limit,
        ACTUAL_UTILIZATION: qvd_data.write_actual_utilization,
    }

    def _write(source: str, rows: Iterable[Mapping[str, Any]]) -> Path:
        return writers[source](Path(configs[source].path), rows)

    return _write


@pytest.fixture
def qvd_service(settings: Settings, source_files) -> QVDService:
    return QVDService(settings)


@pytest.fixture
def service(settings: Settings, source_files) -> ExtensionService:
    """A fully wired service backed by temporary files."""

    return ExtensionService.create_default(settings)


@pytest.fixture
def proof_document() -> PendingDocument:
    return PendingDocument(
        filename="technical_report.pdf",
        data=b"%PDF-1.4 test proof document",
        content_type="application/pdf",
    )


@pytest.fixture
def make_draft(proof_document):
    """Build a draft whose rows already carry their looked-up current values."""

    def _make(
        service: ExtensionService,
        rows: Iterable[tuple[str, str, str]],
        *,
        extension_type: ExtensionType = ExtensionType.ENGINEERING_ORDER,
        extended_hours: float | int | None = 99_000,
        extended_cycles: float | int | None = None,
        extended_days: float | int | None = None,
        documents: Iterable[PendingDocument] | None = None,
        created_by: str = "tester",
    ) -> ExtensionApplicationDraft:
        draft = ExtensionApplicationDraft(
            extension_type=extension_type, created_by=created_by
        )
        draft.documents = list(
            documents if documents is not None else [proof_document]
        )
        for pn, sn, eo in rows:
            row = ExtensionRowDraft(pn=pn, sn=sn, eo=eo)
            record = service.lookup_current_values(extension_type, pn, sn, eo)
            if record is not None:
                row.apply_source_record(record)
            row.extended_hours = extended_hours
            row.extended_cycles = extended_cycles
            row.extended_days = extended_days
            draft.rows.append(row)
        return draft

    return _make

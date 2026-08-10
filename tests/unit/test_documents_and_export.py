"""Proof documents (section 59) and export mapping (sections 26, 27, 55)."""

from __future__ import annotations

import csv
from dataclasses import replace

import pytest

from app.config.export_config import ExportColumn, ExportConfig
from app.errors import DocumentError
from app.models.drafts import PendingDocument
from app.models.enums import ExtensionType
from app.models.extension import ExtensionApplication, ProofDocument
from app.services.document_service import DocumentService
from app.services.export_service import ExportService
from app.utils.dates import now_utc
from app.utils.file_utils import sanitize_filename
from tests.unit.test_repositories import make_item


class TestFilenameSafety:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("report.pdf", "report.pdf"),
            ("../../etc/passwd", "passwd"),
            ("/absolute/path/report.pdf", "report.pdf"),
            (r"C:\temp\report.pdf", "report.pdf"),
            ("my report (final).pdf", "my_report_final.pdf"),
            ("..", "document"),
            ("", "document"),
        ],
    )
    def test_names_are_sanitised(self, raw, expected):
        assert sanitize_filename(raw) == expected

    def test_directory_traversal_cannot_escape(self, settings):
        service = DocumentService(settings)
        stored = service.save_documents(
            "EXT-2026-000001",
            [PendingDocument("../../escape.pdf", b"data")],
            "tester",
        )
        path = service.absolute_path(stored[0])
        assert settings.documents_dir in path.parents
        assert path.name == "escape.pdf"

    def test_long_names_are_truncated_but_keep_the_extension(self):
        name = sanitize_filename("a" * 400 + ".pdf")
        assert name.endswith(".pdf")
        assert len(name) <= 120


class TestDocumentStorage:
    def test_documents_are_stored_per_application(self, settings, proof_document):
        service = DocumentService(settings)
        stored = service.save_documents("EXT-2026-000001", [proof_document], "tester")

        assert len(stored) == 1
        document = stored[0]
        assert document.relative_path == "documents/EXT-2026-000001/technical_report.pdf"
        assert service.absolute_path(document).exists()
        assert service.read_document(document) == proof_document.data

    def test_the_original_filename_is_preserved_as_metadata(self, settings):
        service = DocumentService(settings)
        stored = service.save_documents(
            "EXT-2026-000001", [PendingDocument("my report.pdf", b"x")], "tester"
        )
        assert stored[0].original_filename == "my report.pdf"
        assert stored[0].stored_filename == "my_report.pdf"

    def test_colliding_names_do_not_overwrite_each_other(self, settings):
        service = DocumentService(settings)
        stored = service.save_documents(
            "EXT-2026-000001",
            [PendingDocument("report.pdf", b"first"), PendingDocument("report.pdf", b"second")],
            "tester",
        )
        names = {document.stored_filename for document in stored}
        assert names == {"report.pdf", "report_1.pdf"}
        assert service.read_document(stored[0]) == b"first"
        assert service.read_document(stored[1]) == b"second"

    def test_metadata_is_recorded_in_its_own_dataset(self, settings, proof_document):
        service = DocumentService(settings)
        service.save_documents("EXT-2026-000001", [proof_document], "tester")

        documents = DocumentService(settings).documents_for_application("EXT-2026-000001")
        assert len(documents) == 1
        assert documents[0].uploaded_by == "tester"
        assert documents[0].size_bytes == len(proof_document.data)
        assert documents[0].uploaded_at is not None

    def test_binaries_never_enter_the_database(self, settings, proof_document):
        service = DocumentService(settings)
        service.save_documents("EXT-2026-000001", [proof_document], "tester")
        stored = settings.documents_file.read_bytes()
        assert proof_document.data not in stored

    def test_oversized_documents_are_refused(self, settings):
        strict = replace(settings, max_document_size_mb=0.000_01)
        service = DocumentService(strict)
        with pytest.raises(DocumentError) as exc:
            service.save_documents(
                "EXT-2026-000001", [PendingDocument("big.pdf", b"x" * 1024)], "tester"
            )
        assert "exceeds" in exc.value.user_message

    def test_unsupported_types_are_refused(self, settings):
        service = DocumentService(settings)
        with pytest.raises(DocumentError):
            service.save_documents(
                "EXT-2026-000001", [PendingDocument("script.exe", b"MZ")], "tester"
            )

    def test_discard_removes_a_failed_applications_files(self, settings, proof_document):
        service = DocumentService(settings)
        service.save_documents("EXT-2026-000001", [proof_document], "tester", register=False)
        assert service.application_directory("EXT-2026-000001").exists()

        service.discard_documents("EXT-2026-000001")
        assert not service.application_directory("EXT-2026-000001").exists()


class TestExportMapping:
    def _application(self):
        item = make_item()
        return ExtensionApplication(
            application_id=item.application_id,
            extension_type=ExtensionType.ENGINEERING_ORDER,
            created_at=item.created_at,
            created_by="tester",
            proof_documents=(
                ProofDocument(
                    document_id="EXT-2026-000001-DOC-001",
                    application_id=item.application_id,
                    original_filename="technical_report.pdf",
                    stored_filename="technical_report.pdf",
                    relative_path="documents/EXT-2026-000001/technical_report.pdf",
                    uploaded_at=now_utc(),
                    uploaded_by="tester",
                ),
            ),
            extension_items=(item,),
        )

    def test_the_default_template_is_applied(self, settings):
        service = ExportService(settings)
        path = service.export_application(self._application())

        assert path.exists()
        with path.open(encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
        assert rows[0][:6] == [
            "Application ID",
            "Extension ID",
            "Extension Type",
            "PN",
            "SN",
            "EO",
        ]
        assert rows[1][0] == "EXT-2026-000001"
        assert rows[1][3] == "PN001"

    def test_dates_are_formatted_only_in_the_export(self, settings):
        service = ExportService(settings)
        rows = service.map_rows(self._application().extension_items, self._application())
        headers = service.headers
        assert rows[0][headers.index("Current Date")] == "01-Aug-2026"

    def test_missing_values_stay_empty_rather_than_becoming_zero(self, settings):
        service = ExportService(settings)
        application = self._application()
        rows = service.map_rows(application.extension_items, application)
        assert rows[0][service.headers.index("Extended Cycles")] == ""

    def test_document_names_are_carried_into_the_export(self, settings):
        application = self._application()
        service = ExportService(settings)
        rows = service.map_rows(
            application.extension_items, application, application.proof_documents
        )
        assert rows[0][service.headers.index("Proof Documents")] == "technical_report.pdf"

    def test_the_layout_is_configuration_not_code(self, settings):
        """Section 26: the export layout can change without touching storage."""

        custom = ExportConfig(
            columns=(
                ExportColumn("PART", "pn"),
                ExportColumn("NEW LIMIT", "extended_hours", "number"),
                ExportColumn("RAISED", "created_at", "date"),
            ),
            filename_template="{application_id}_custom",
        )
        service = ExportService(settings, custom)
        path = service.export_application(self._application())

        with path.open(encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == ["PART", "NEW LIMIT", "RAISED"]
        assert rows[1][0] == "PN001"
        assert rows[1][1] == "13000"
        assert path.name.endswith("_custom.csv")

    def test_an_xlsx_export_can_be_configured(self, settings):
        pytest.importorskip("openpyxl")
        service = ExportService(
            settings, replace(ExportConfig(columns=(ExportColumn("PN", "pn"),)), file_format="xlsx")
        )
        path = service.export_application(self._application())
        assert path.suffix == ".xlsx"
        assert path.exists()

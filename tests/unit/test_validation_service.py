"""Business rule validation (specification sections 14, 15, 17, 18 and 65)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from app.config.qvd_config import ENGINEERING_ORDER
from app.config.settings import set_settings
from app.models.drafts import ExtensionApplicationDraft, ExtensionRowDraft, PendingDocument
from app.models.enums import DuplicatePolicy, ExtensionType, Severity
from app.services.extension_service import ExtensionService
from app.utils.dates import UTC
from tests.fixtures import qvd_data


def codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


class TestSubmissionPrerequisites:
    def test_a_draft_without_rows_is_rejected(self, service, proof_document):
        draft = ExtensionApplicationDraft(
            extension_type=ExtensionType.ENGINEERING_ORDER, documents=[proof_document]
        )
        result = service.validate(draft)
        assert not result.ok
        assert "no_rows" in codes(result)

    def test_a_draft_without_an_extension_type_is_rejected(self, service, proof_document):
        draft = ExtensionApplicationDraft(documents=[proof_document])
        assert "extension_type_missing" in codes(service.validate(draft))

    def test_proof_documents_are_required_by_default(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")], documents=[])
        assert "proof_documents_missing" in codes(service.validate(draft))

    def test_the_requirement_is_configuration_not_code(self, settings, source_files):
        relaxed = replace(settings, require_proof_documents=False)
        set_settings(relaxed)
        service = ExtensionService.create_default(relaxed)

        draft = ExtensionApplicationDraft(extension_type=ExtensionType.ENGINEERING_ORDER)
        row = ExtensionRowDraft(pn="PN001", sn="SN001", eo="EO001")
        row.apply_source_record(
            service.lookup_current_values(
                ExtensionType.ENGINEERING_ORDER, "PN001", "SN001", "EO001"
            )
        )
        row.extended_hours = 13000
        draft.rows.append(row)

        assert service.validate(draft).ok

    def test_unsupported_document_types_are_rejected(self, service, make_draft):
        draft = make_draft(
            service,
            [("PN001", "SN001", "EO001")],
            documents=[PendingDocument("malware.exe", b"MZ...")],
        )
        result = service.validate(draft)
        assert "document_rejected" in codes(result)
        assert any("unsupported file type" in message for message in result.error_messages())


class TestIdentifiers:
    @pytest.mark.parametrize("missing", ["pn", "sn", "eo"])
    def test_every_identifier_is_required(self, service, make_draft, missing):
        draft = make_draft(service, [("PN001", "SN001", "EO001")])
        setattr(draft.rows[0], missing, "")
        assert "identifier_missing" in codes(service.validate(draft))

    def test_a_row_with_no_source_record_cannot_be_submitted(self, service, make_draft):
        """Section 14: the row must not be submitted until resolved."""

        draft = make_draft(service, [("PN999", "SN999", "EO999")])
        result = service.validate(draft)
        assert not result.ok
        assert "source_not_found" in codes(result)
        assert any("No matching source record" in m for m in result.error_messages())

    def test_current_values_must_have_been_retrieved(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")])
        draft.rows[0].clear_source_record()
        assert "current_values_not_loaded" in codes(service.validate(draft))

    def test_ambiguous_source_data_blocks_the_row(self, service, write_source, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")])
        write_source(
            ENGINEERING_ORDER,
            [
                qvd_data.row("PN001", "SN001", "EO001", hours=12000),
                qvd_data.row("PN001", "SN001", "EO001", hours=12500),
            ],
        )
        result = service.validate(draft)
        assert "source_ambiguous" in codes(result)
        assert any("Multiple source records" in m for m in result.error_messages())


class TestExtendedValues:
    def test_at_least_one_extended_value_is_required(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")], extended_hours=None)
        assert "no_extended_value" in codes(service.validate(draft))

    def test_non_numeric_extended_values_are_rejected(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")])
        draft.rows[0].extended_hours = "twelve thousand"
        assert "extended_not_numeric" in codes(service.validate(draft))

    def test_negative_values_are_rejected(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")], extended_hours=-5)
        assert "extended_negative" in codes(service.validate(draft))

    def test_extended_below_current_is_rejected(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")], extended_hours=11_000)
        result = service.validate(draft)
        assert "extended_below_current" in codes(result)

    def test_a_missing_dimension_is_allowed(self, service, make_draft):
        """NULL means 'not applicable', which is valid (section 15)."""

        draft = make_draft(
            service,
            [("PN001", "SN001", "EO001")],
            extended_hours=13000,
            extended_cycles=None,
            extended_days=None,
        )
        assert service.validate(draft).ok

    def test_zero_is_treated_as_a_value_not_as_missing(self, service, make_draft):
        draft = make_draft(
            service, [("PN001", "SN001", "EO001")], extended_hours=None, extended_cycles=0
        )
        result = service.validate(draft)
        assert "no_extended_value" not in codes(result)
        # 0 is below the current cycles, so the comparison rule catches it.
        assert "extended_below_current" in codes(result)

    def test_an_extended_date_alone_satisfies_the_rule(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")], extended_hours=None)
        draft.rows[0].extended_date = datetime(2027, 1, 1, tzinfo=UTC)
        assert service.validate(draft).ok

    def test_an_extended_date_before_the_current_date_is_rejected(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")])
        draft.rows[0].extended_date = datetime(2020, 1, 1, tzinfo=UTC)
        assert "extended_date_before_current" in codes(service.validate(draft))

    def test_an_invalid_date_is_reported(self, service, make_draft):
        draft = make_draft(service, [("PN001", "SN001", "EO001")])
        draft.rows[0].extended_date = "the thirty-first of Smarch"
        assert "extended_date_invalid" in codes(service.validate(draft))


class TestDuplicates:
    def test_a_duplicate_row_within_one_submission_is_rejected(self, service, make_draft):
        draft = make_draft(
            service, [("PN001", "SN001", "EO001"), ("PN001", "SN001", "EO001")]
        )
        assert "duplicate_in_submission" in codes(service.validate(draft))

    def test_normalised_duplicates_are_detected(self, service, make_draft):
        draft = make_draft(
            service, [("PN001", "SN001", "EO001"), (" pn001 ", "sn001", "eo001")]
        )
        assert "duplicate_in_submission" in codes(service.validate(draft))

    def test_an_existing_active_extension_blocks_a_new_one(self, service, make_draft):
        """Section 18 with the default BLOCK policy."""

        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]))
        result = service.validate(make_draft(service, [("PN001", "SN001", "EO001")]))
        assert not result.ok
        assert "duplicate_active_extension" in codes(result)

    def test_the_policy_is_configurable_to_warn(self, settings, source_files, make_draft):
        warned = replace(settings, duplicate_policy=DuplicatePolicy.WARN)
        set_settings(warned)
        service = ExtensionService.create_default(warned)

        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]))
        result = service.validate(make_draft(service, [("PN001", "SN001", "EO001")]))
        assert result.ok
        assert any(issue.severity is Severity.WARNING for issue in result.issues)

    def test_the_policy_is_configurable_to_allow(self, settings, source_files, make_draft):
        allowed = replace(settings, duplicate_policy=DuplicatePolicy.ALLOW)
        set_settings(allowed)
        service = ExtensionService.create_default(allowed)

        service.create_extension(make_draft(service, [("PN001", "SN001", "EO001")]))
        result = service.validate(make_draft(service, [("PN001", "SN001", "EO001")]))
        assert result.ok
        assert not result.warnings


class TestIssueReporting:
    def test_issues_name_the_row_they_belong_to(self, service, make_draft):
        draft = make_draft(
            service, [("PN001", "SN001", "EO001"), ("PN999", "SN999", "EO999")]
        )
        result = service.validate(draft)
        assert [issue.row_number for issue in result.errors] == [2]
        assert result.error_messages()[0].startswith("Row 2:")

    def test_messages_are_business_readable(self, service, make_draft):
        draft = make_draft(service, [("PN999", "SN999", "EO999")])
        for message in service.validate(draft).error_messages():
            assert "Error" not in message
            assert "Traceback" not in message

"""Business rule validation (specification sections 17 and 18).

Deliberately separate from the UI: the screens render whatever this service
reports and never decide policy themselves.  In particular the duplicate rule
is configuration, not an implicit decision buried in a form handler
(section 85 rule 1 and section 18).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

from app.config.settings import Settings, get_settings
from app.errors import AmbiguousQVDRecordError, QVDError
from app.models.drafts import ExtensionApplicationDraft, ExtensionRowDraft
from app.models.enums import DuplicatePolicy, Severity
from app.repositories.active_extension_repository import ActiveExtensionRepository
from app.services.document_service import DocumentService
from app.services.qvd_service import QVDService
from app.utils.dates import parse_optional_datetime
from app.utils.logging_utils import AuditEvent, get_logger, log_event
from app.utils.normalize import is_null_like, normalize_number

#: Dimensions a user may extend.
EXTENDED_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("extended_hours", "Extended Hours"),
    ("extended_cycles", "Extended Cycles"),
    ("extended_days", "Extended Days"),
)

CURRENT_OF_EXTENDED = {
    "extended_hours": ("current_hours", "Current Hours"),
    "extended_cycles": ("current_cycles", "Current Cycles"),
    "extended_days": ("current_days", "Current Days"),
}


@dataclass(frozen=True)
class ValidationIssue:
    """One problem found in a draft submission."""

    code: str
    message: str
    severity: Severity = Severity.ERROR
    row_number: int | None = None
    field_name: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR

    def describe(self) -> str:
        if self.row_number is None:
            return self.message
        return f"Row {self.row_number}: {self.message}"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a draft."""

    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.is_error)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.is_error)

    @property
    def ok(self) -> bool:
        """True when nothing blocks submission."""

        return not self.errors

    def messages(self) -> list[str]:
        return [issue.describe() for issue in self.issues]

    def error_messages(self) -> list[str]:
        return [issue.describe() for issue in self.errors]

    def for_row(self, row_number: int) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.row_number == row_number)


class ValidationService:
    """Validates a draft application before anything is written."""

    def __init__(
        self,
        settings: Settings | None = None,
        qvd_service: QVDService | None = None,
        active_repository: ActiveExtensionRepository | None = None,
        document_service: DocumentService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.qvd_service = qvd_service or QVDService(self.settings)
        self.active_repository = active_repository or ActiveExtensionRepository(self.settings)
        self.document_service = document_service or DocumentService(self.settings)
        self.logger = get_logger("validation")

    # --- public API ------------------------------------------------------
    def validate_application(self, draft: ExtensionApplicationDraft) -> ValidationResult:
        issues: list[ValidationIssue] = []

        if draft.extension_type is None:
            issues.append(
                ValidationIssue(
                    "extension_type_missing",
                    "Select an extension type before applying.",
                )
            )

        issues.extend(self._validate_documents(draft))

        if not draft.rows:
            issues.append(
                ValidationIssue(
                    "no_rows",
                    "Add at least one extension row before applying.",
                )
            )

        seen_keys: dict[tuple, int] = {}
        for position, row in enumerate(draft.rows, start=1):
            issues.extend(self._validate_row(draft, row, position))
            issues.extend(self._check_within_submission(row, position, seen_keys))

        if draft.extension_type is not None:
            issues.extend(self._check_against_active(draft.rows))

        result = ValidationResult(tuple(issues))
        if not result.ok:
            log_event(
                self.logger,
                AuditEvent.VALIDATION_FAILED,
                rows=len(draft.rows),
                errors=len(result.errors),
                first_error=result.error_messages()[0][:80],
            )
        return result

    # --- documents -------------------------------------------------------
    def _validate_documents(
        self, draft: ExtensionApplicationDraft
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        minimum = self.settings.min_proof_documents if self.settings.require_proof_documents else 0
        if len(draft.documents) < minimum:
            noun = "document" if minimum == 1 else "documents"
            issues.append(
                ValidationIssue(
                    "proof_documents_missing",
                    f"Attach at least {minimum} proof {noun} before applying.",
                )
            )
        for problem in self.document_service.validate_documents(draft.documents):
            issues.append(ValidationIssue("document_rejected", problem))
        return issues

    # --- one row ---------------------------------------------------------
    def _validate_row(
        self,
        draft: ExtensionApplicationDraft,
        row: ExtensionRowDraft,
        position: int,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        for field_name, label in (("pn", "PN"), ("sn", "SN"), ("eo", "EO")):
            if is_null_like(getattr(row, field_name)):
                issues.append(
                    ValidationIssue(
                        "identifier_missing",
                        f"{label} is required.",
                        row_number=position,
                        field_name=field_name,
                    )
                )
        if issues:
            return issues

        issues.extend(self._validate_source_record(draft, row, position))
        issues.extend(self._validate_extended_values(row, position))
        return issues

    def _validate_source_record(
        self,
        draft: ExtensionApplicationDraft,
        row: ExtensionRowDraft,
        position: int,
    ) -> list[ValidationIssue]:
        """PN/SN/EO must resolve to exactly one source record (sections 14, 65)."""

        if draft.extension_type is None:
            return []
        try:
            record = self.qvd_service.lookup_extension_record(
                draft.extension_type, row.pn, row.sn, row.eo
            )
        except AmbiguousQVDRecordError as exc:
            return [
                ValidationIssue(
                    "source_ambiguous",
                    exc.user_message,
                    row_number=position,
                )
            ]
        except QVDError as exc:
            return [
                ValidationIssue("source_unavailable", exc.user_message, row_number=position)
            ]

        if record is None:
            return [
                ValidationIssue(
                    "source_not_found",
                    "No matching source record found for this PN / SN / EO combination.",
                    row_number=position,
                )
            ]

        if not row.lookup_done:
            return [
                ValidationIssue(
                    "current_values_not_loaded",
                    "Current values have not been retrieved yet. Use Find to load them.",
                    row_number=position,
                )
            ]
        return []

    def _validate_extended_values(
        self, row: ExtensionRowDraft, position: int
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        provided = 0

        for field_name, label in EXTENDED_DIMENSIONS:
            raw = getattr(row, field_name)
            if is_null_like(raw):
                continue  # NULL is a valid, distinct state (section 15)
            try:
                value = normalize_number(raw)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        "extended_not_numeric",
                        f"{label} must be a number.",
                        row_number=position,
                        field_name=field_name,
                    )
                )
                continue
            if value is None:
                continue
            provided += 1

            if value < 0 and not self.settings.allow_negative_values:
                issues.append(
                    ValidationIssue(
                        "extended_negative",
                        f"{label} cannot be negative.",
                        row_number=position,
                        field_name=field_name,
                    )
                )
                continue

            if self.settings.require_extended_above_current:
                current_field, current_label = CURRENT_OF_EXTENDED[field_name]
                current = getattr(row, current_field)
                if current is not None and value < current:
                    issues.append(
                        ValidationIssue(
                            "extended_below_current",
                            f"{label} ({_number(value)}) is lower than "
                            f"{current_label} ({_number(current)}).",
                            row_number=position,
                            field_name=field_name,
                        )
                    )

        extended_date = self._validated_date(row.extended_date, position, issues)
        if extended_date is not None:
            provided += 1
            if row.current_date is not None and extended_date < row.current_date:
                issues.append(
                    ValidationIssue(
                        "extended_date_before_current",
                        "Extended Date is earlier than the current source date.",
                        row_number=position,
                        field_name="extended_date",
                    )
                )

        if provided == 0 and self.settings.require_at_least_one_extended_dimension:
            issues.append(
                ValidationIssue(
                    "no_extended_value",
                    "Enter at least one extended value (hours, cycles, days or date).",
                    row_number=position,
                )
            )
        return issues

    @staticmethod
    def _validated_date(
        value: Any, position: int, issues: list[ValidationIssue]
    ) -> datetime | None:
        if is_null_like(value):
            return None
        parsed = parse_optional_datetime(value)
        if parsed is None:
            issues.append(
                ValidationIssue(
                    "extended_date_invalid",
                    "Extended Date is not a valid date.",
                    row_number=position,
                    field_name="extended_date",
                )
            )
        return parsed

    # --- duplicates ------------------------------------------------------
    @staticmethod
    def _check_within_submission(
        row: ExtensionRowDraft, position: int, seen: dict[tuple, int]
    ) -> list[ValidationIssue]:
        if not row.identifiers_complete:
            return []
        first = seen.get(row.key)
        if first is not None:
            return [
                ValidationIssue(
                    "duplicate_in_submission",
                    f"This PN / SN / EO combination is already entered in row {first}.",
                    row_number=position,
                )
            ]
        seen[row.key] = position
        return []

    def _check_against_active(
        self, rows: Sequence[ExtensionRowDraft]
    ) -> list[ValidationIssue]:
        """Apply the configured duplicate policy (section 18)."""

        policy = self.settings.duplicate_policy
        if policy is DuplicatePolicy.ALLOW:
            return []

        candidates = {row.key for row in rows if row.identifiers_complete}
        if not candidates:
            return []

        existing = {item.key: item for item in self.active_repository.read_items()}
        severity = Severity.ERROR if policy is DuplicatePolicy.BLOCK else Severity.WARNING
        issues: list[ValidationIssue] = []
        for position, row in enumerate(rows, start=1):
            if not row.identifiers_complete:
                continue
            match = existing.get(row.key)
            if match is None:
                continue
            issues.append(
                ValidationIssue(
                    "duplicate_active_extension",
                    (
                        f"An active extension already exists for {row.pn} / {row.sn} / {row.eo} "
                        f"({match.extension_id})."
                    ),
                    severity=severity,
                    row_number=position,
                )
            )
        return issues


def _number(value: float | int) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def issues_to_messages(issues: Iterable[ValidationIssue]) -> list[str]:
    return [issue.describe() for issue in issues]

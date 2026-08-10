"""Application settings.

Nothing in this application may hard-code a production path, folder or
business policy (specification section 54).  Everything lives here and can be
overridden with environment variables prefixed with ``EXTMGMT_`` or, in tests,
by building a :class:`Settings` instance rooted at a temporary directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.models.enums import DuplicatePolicy

ENV_PREFIX = "EXTMGMT_"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(ENV_PREFIX + name, default)


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    raw = _env(name)
    return Path(raw).expanduser() if raw else default


def _env_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _env(name)
    if raw is None:
        return default
    parts = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return tuple(parts) or default


def _project_root() -> Path:
    # app/config/settings.py -> app/config -> app -> project root
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Immutable application configuration."""

    # --- locations -------------------------------------------------------
    project_root: Path
    data_dir: Path
    active_dir: Path
    completed_dir: Path
    deleted_dir: Path
    documents_dir: Path
    exports_dir: Path
    backup_dir: Path
    qvd_dir: Path
    logs_dir: Path

    active_file_name: str = "extensions.parquet"
    completed_file_name: str = "completed_extensions.parquet"
    deleted_file_name: str = "deleted_extensions.parquet"
    documents_file_name: str = "documents.parquet"
    lock_file_name: str = "extensions.lock"
    log_file_name: str = "extension_management.log"

    # --- storage behaviour ----------------------------------------------
    lock_timeout_seconds: float = 30.0
    backup_enabled: bool = True
    backup_retention: int = 20

    # --- document policy (section 59 / 87) -------------------------------
    require_proof_documents: bool = True
    min_proof_documents: int = 1
    max_document_size_mb: float = 25.0
    allowed_document_extensions: tuple[str, ...] = (
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".msg",
        ".eml",
        ".png",
        ".jpg",
        ".jpeg",
        ".txt",
        ".csv",
    )

    # --- business rules (section 87 - parameterised until specified) -----
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.BLOCK
    allow_negative_values: bool = False
    require_extended_above_current: bool = True
    require_at_least_one_extended_dimension: bool = True

    # Optional utilisation monitoring (section 37). Off by default: the
    # application must never complete an extension by itself.
    limit_monitoring_enabled: bool = False
    approaching_limit_ratio: float = 0.9

    # --- identity / presentation -----------------------------------------
    default_user: str = "unknown"
    display_date_format: str = "%d-%b-%Y"
    display_datetime_format: str = "%d-%b-%Y %H:%M"

    # --- misc -------------------------------------------------------------
    application_id_prefix: str = "EXT"
    log_level: str = "INFO"
    extra: dict = field(default_factory=dict)

    # --- derived paths ----------------------------------------------------
    @property
    def active_file(self) -> Path:
        return self.active_dir / self.active_file_name

    @property
    def completed_file(self) -> Path:
        return self.completed_dir / self.completed_file_name

    @property
    def deleted_file(self) -> Path:
        return self.deleted_dir / self.deleted_file_name

    @property
    def documents_file(self) -> Path:
        return self.data_dir / self.documents_file_name

    @property
    def lock_file(self) -> Path:
        return self.data_dir / self.lock_file_name

    @property
    def log_file(self) -> Path:
        return self.logs_dir / self.log_file_name

    @property
    def max_document_size_bytes(self) -> int:
        return int(self.max_document_size_mb * 1024 * 1024)

    # --- factories --------------------------------------------------------
    @classmethod
    def for_root(cls, root: Path | str, **overrides) -> "Settings":
        """Build a settings object with every path derived from ``root``.

        Used by tests and by throwaway environments so no production path is
        ever touched.
        """

        root = Path(root).expanduser()
        data_dir = root / "data"
        base = cls(
            project_root=root,
            data_dir=data_dir,
            active_dir=data_dir / "active",
            completed_dir=data_dir / "completed",
            deleted_dir=data_dir / "deleted",
            documents_dir=data_dir / "documents",
            exports_dir=data_dir / "exports",
            backup_dir=data_dir / "backup",
            qvd_dir=data_dir / "qvd",
            logs_dir=root / "logs",
        )
        return replace(base, **overrides) if overrides else base

    @classmethod
    def from_env(cls) -> "Settings":
        root = _env_path("PROJECT_ROOT", _project_root())
        data_dir = _env_path("DATA_DIR", root / "data")
        return cls(
            project_root=root,
            data_dir=data_dir,
            active_dir=_env_path("ACTIVE_DIR", data_dir / "active"),
            completed_dir=_env_path("COMPLETED_DIR", data_dir / "completed"),
            deleted_dir=_env_path("DELETED_DIR", data_dir / "deleted"),
            documents_dir=_env_path("DOCUMENTS_DIR", data_dir / "documents"),
            exports_dir=_env_path("EXPORTS_DIR", data_dir / "exports"),
            backup_dir=_env_path("BACKUP_DIR", data_dir / "backup"),
            qvd_dir=_env_path("QVD_DIR", data_dir / "qvd"),
            logs_dir=_env_path("LOGS_DIR", root / "logs"),
            lock_timeout_seconds=_env_float("LOCK_TIMEOUT_SECONDS", 30.0),
            backup_enabled=_env_bool("BACKUP_ENABLED", True),
            backup_retention=_env_int("BACKUP_RETENTION", 20),
            require_proof_documents=_env_bool("REQUIRE_PROOF_DOCUMENTS", True),
            min_proof_documents=_env_int("MIN_PROOF_DOCUMENTS", 1),
            max_document_size_mb=_env_float("MAX_DOCUMENT_SIZE_MB", 25.0),
            allowed_document_extensions=_env_tuple(
                "ALLOWED_DOCUMENT_EXTENSIONS",
                cls.allowed_document_extensions,
            ),
            duplicate_policy=DuplicatePolicy.parse(
                _env("DUPLICATE_POLICY"), DuplicatePolicy.BLOCK
            ),
            allow_negative_values=_env_bool("ALLOW_NEGATIVE_VALUES", False),
            require_extended_above_current=_env_bool(
                "REQUIRE_EXTENDED_ABOVE_CURRENT", True
            ),
            require_at_least_one_extended_dimension=_env_bool(
                "REQUIRE_ONE_EXTENDED_DIMENSION", True
            ),
            limit_monitoring_enabled=_env_bool("LIMIT_MONITORING_ENABLED", False),
            approaching_limit_ratio=_env_float("APPROACHING_LIMIT_RATIO", 0.9),
            default_user=_env("DEFAULT_USER") or os.environ.get("USER") or "unknown",
            display_date_format=_env("DISPLAY_DATE_FORMAT", "%d-%b-%Y"),
            display_datetime_format=_env("DISPLAY_DATETIME_FORMAT", "%d-%b-%Y %H:%M"),
            application_id_prefix=_env("APPLICATION_ID_PREFIX", "EXT"),
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        )

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.active_dir,
            self.completed_dir,
            self.deleted_dir,
            self.documents_dir,
            self.exports_dir,
            self.backup_dir,
            self.qvd_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process wide settings, building them from the environment."""

    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def set_settings(settings: Settings | None) -> None:
    """Replace the process wide settings (used by tests and by ``main.py``)."""

    global _settings
    _settings = settings


def reset_settings() -> None:
    set_settings(None)

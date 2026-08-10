"""File system helpers, primarily for safe proof-document storage.

Section 59: sanitise filenames, prevent directory traversal, avoid
collisions, preserve the original name as metadata.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePath, PureWindowsPath

MAX_FILENAME_LENGTH = 120
FALLBACK_FILENAME = "document"

_ALLOWED = re.compile(r"[^A-Za-z0-9._-]+")
_REPEATED_SEPARATORS = re.compile(r"[_.-]{2,}")

#: Names that cannot be used as files on Windows shares.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def sanitize_filename(filename: str, *, fallback: str = FALLBACK_FILENAME) -> str:
    """Return a safe file name with no path component.

    ``../../etc/passwd`` becomes ``passwd``; ``C:\\temp\\report.pdf`` becomes
    ``report.pdf``.  The extension is preserved because document policy is
    driven by it.
    """

    raw = str(filename or "").strip()
    # Strip both POSIX and Windows path components before anything else.
    raw = PureWindowsPath(raw.replace("/", "\\")).name
    raw = PurePath(raw).name
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw = raw.replace(" ", "_")

    suffix = PurePath(raw).suffix
    stem = raw[: len(raw) - len(suffix)] if suffix else raw

    stem = _ALLOWED.sub("_", stem).strip("._-")
    stem = _REPEATED_SEPARATORS.sub("_", stem)
    suffix = _ALLOWED.sub("", suffix)

    if not stem or stem.lower() in _RESERVED:
        stem = fallback if not stem else f"{fallback}_{stem}"

    max_stem = MAX_FILENAME_LENGTH - len(suffix)
    if max_stem < 1:
        suffix = suffix[:MAX_FILENAME_LENGTH]
        max_stem = 1
    stem = stem[:max_stem]
    return f"{stem}{suffix.lower()}"


def file_extension(filename: str) -> str:
    """Lower case extension including the leading dot ("" when absent)."""

    return PurePath(sanitize_filename(filename)).suffix.lower()


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_path(directory: Path, filename: str) -> Path:
    """Return a path inside ``directory`` that does not exist yet."""

    safe = sanitize_filename(filename)
    candidate = directory / safe
    if not candidate.exists():
        return candidate

    suffix = PurePath(safe).suffix
    stem = safe[: len(safe) - len(suffix)] if suffix else safe
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def is_within(path: Path, parent: Path) -> bool:
    """Guard against escaping a storage root via symlinks or ``..``."""

    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except (ValueError, OSError):
        return False
    return True


def relative_to_root(path: Path, root: Path) -> str:
    """Path stored in the database: relative to the data root, POSIX style."""

    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def human_size(num_bytes: float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # pragma: no cover - unreachable

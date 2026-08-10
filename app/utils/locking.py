"""Cross process write lock (specification section 25).

Two users must never load the same Parquet snapshot and then overwrite each
other.  Every mutating transaction runs inside :func:`write_lock`.

``filelock`` is used when installed; otherwise a small ``O_EXCL`` based lock
with stale-lock recovery is used so the application still runs on a bare
Python installation.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Iterator

from app.errors import LockTimeoutError

try:  # pragma: no cover - depends on the installed environment
    from filelock import FileLock as _ExternalFileLock
    from filelock import Timeout as _ExternalTimeout

    _HAS_FILELOCK = True
except Exception:  # pragma: no cover
    _ExternalFileLock = None
    _ExternalTimeout = None
    _HAS_FILELOCK = False

#: A lock older than this is considered abandoned by a crashed process.
STALE_LOCK_SECONDS = 300.0


class _FallbackLock:
    """Minimal advisory lock used when ``filelock`` is unavailable."""

    def __init__(self, path: Path, timeout: float) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode("ascii"))
                return
            except FileExistsError:
                if self._clear_if_stale():
                    continue
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        "Timed out waiting for the extension database write lock",
                        lock_file=str(self.path),
                        timeout=self.timeout,
                    )
                time.sleep(0.1)

    def _clear_if_stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return True
        if age > STALE_LOCK_SECONDS:
            with contextlib.suppress(OSError):
                self.path.unlink()
                return True
        return False

    def release(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
        with contextlib.suppress(OSError):
            self.path.unlink()


@contextlib.contextmanager
def write_lock(lock_file: Path, timeout: float = 30.0) -> Iterator[None]:
    """Hold the exclusive write lock for the duration of the block."""

    lock_file = Path(lock_file)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    if _HAS_FILELOCK:
        lock = _ExternalFileLock(str(lock_file), timeout=timeout)
        try:
            lock.acquire()
        except _ExternalTimeout as exc:
            raise LockTimeoutError(
                "Timed out waiting for the extension database write lock",
                lock_file=str(lock_file),
                timeout=timeout,
            ) from exc
        try:
            yield
        finally:
            lock.release()
        return

    fallback = _FallbackLock(lock_file, timeout)
    fallback.acquire()
    try:
        yield
    finally:
        fallback.release()

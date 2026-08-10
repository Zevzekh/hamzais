"""Entry point for the Extension Management application.

Run the user interface::

    streamlit run main.py

Check the configuration and data locations without starting a server::

    python main.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config.qvd_config import build_qvd_config  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.utils.logging_utils import configure_logging  # noqa: E402


def bootstrap():
    """Prepare settings, folders and logging. Safe to call repeatedly."""

    settings = get_settings()
    settings.ensure_directories()
    configure_logging(settings)
    return settings


def _check() -> int:
    settings = bootstrap()
    print("Extension Management — configuration")
    print(f"  project root      : {settings.project_root}")
    print(f"  active database   : {settings.active_file}")
    print(f"  completed archive : {settings.completed_file}")
    print(f"  deleted archive   : {settings.deleted_file}")
    print(f"  documents         : {settings.documents_dir}")
    print(f"  exports           : {settings.exports_dir}")
    print(f"  log file          : {settings.log_file}")
    print(f"  duplicate policy  : {settings.duplicate_policy.value}")
    print("  source data:")

    missing = 0
    for name, config in build_qvd_config(settings).items():
        status = "found" if Path(config.path).exists() else "MISSING"
        if status == "MISSING":
            missing += 1
        print(f"    {name:<20} {status:<8} {config.reader:<8} {config.path}")

    if missing:
        print(
            f"\n{missing} source file(s) missing. "
            "Run 'python scripts/seed_sample_data.py' to create sample data."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="print the resolved configuration and exit"
    )
    args = parser.parse_args()
    if args.check:
        return _check()

    print(__doc__)
    print("Start the user interface with:  streamlit run main.py")
    return 0


bootstrap()

def _running_under_streamlit() -> bool:
    """True when this file was started by 'streamlit run'."""

    try:
        from streamlit.runtime import exists
    except Exception:  # pragma: no cover - streamlit not installed
        return False
    return bool(exists())


if __name__ == "__main__":
    if _running_under_streamlit():
        from app.ui.app import run

        run()
    else:
        raise SystemExit(main())

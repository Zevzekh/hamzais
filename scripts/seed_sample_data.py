"""Generate sample source data so the application can be run and demonstrated.

Automated tests never touch these files - they build their own fixtures
(specification section 73).  This script exists so a developer can start the
UI without access to any production source.

Usage::

    python scripts/seed_sample_data.py [--force]
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.qvd_config import (  # noqa: E402
    ACTUAL_UTILIZATION,
    ENGINEERING_ORDER,
    HARD_TIME_LIMIT,
    build_qvd_config,
)
from app.config.settings import get_settings  # noqa: E402

PART_NUMBERS = [f"PN{index:03d}" for index in range(1, 21)]
ENGINEERING_ORDERS = [f"EO-{1000 + index}" for index in range(1, 21)]
TASK_REFERENCES = [f"HTL-{2000 + index}" for index in range(1, 21)]


def _rows(count: int, eo_values: list[str], seed: int, days_back: int):
    rng = random.Random(seed)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for index in range(count):
        hours = rng.randrange(4_000, 20_000)
        yield {
            "pn": PART_NUMBERS[index % len(PART_NUMBERS)],
            "sn": f"SN{index + 1:03d}",
            "eo": eo_values[index % len(eo_values)],
            "hours": hours,
            "cycles": int(hours * rng.uniform(0.55, 0.75)),
            "days": int(hours * rng.uniform(0.10, 0.14)),
            "reference": today - timedelta(days=rng.randrange(1, 30)),
            "modified": today - timedelta(days=rng.randrange(0, days_back)),
        }


def write_engineering_order(path: Path) -> int:
    rows = list(_rows(20, ENGINEERING_ORDERS, seed=11, days_back=45))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "PART_NUMBER",
                "SERIAL_NUMBER",
                "ENGINEERING_ORDER",
                "CURRENT_HOURS",
                "CURRENT_CYCLES",
                "CURRENT_DAYS",
                "CURRENT_DATE",
                "MODIFIED_DATE",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["pn"],
                    row["sn"],
                    row["eo"],
                    row["hours"],
                    row["cycles"],
                    row["days"],
                    row["reference"].strftime("%Y-%m-%d"),
                    row["modified"].strftime("%Y-%m-%d"),
                ]
            )
    return len(rows)


def write_hard_time_limit(path: Path) -> int:
    rows = list(_rows(20, TASK_REFERENCES, seed=23, days_back=60))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "PART_NUMBER",
                "SERIAL_NUMBER",
                "TASK_REFERENCE",
                "CURRENT_HOURS",
                "CURRENT_CYCLES",
                "CURRENT_DAYS",
                "CURRENT_DATE",
                "MODIFIED_DATE",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["pn"],
                    row["sn"],
                    row["eo"],
                    row["hours"],
                    row["cycles"],
                    row["days"],
                    row["reference"].strftime("%Y-%m-%d"),
                    row["modified"].strftime("%Y-%m-%d"),
                ]
            )
    return len(rows)


def write_actual_utilization(path: Path) -> int:
    """Operational data: the same fleet, a little further along in life."""

    rng = random.Random(37)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = list(_rows(20, ENGINEERING_ORDERS, seed=11, days_back=45))
    rows += list(_rows(20, TASK_REFERENCES, seed=23, days_back=60))

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "PART_NUMBER",
                "SERIAL_NUMBER",
                "ENGINEERING_ORDER",
                "ACTUAL_HOURS",
                "ACTUAL_CYCLES",
                "ACTUAL_DAYS",
                "ACTUAL_DATE",
                "MODIFIED_DATE",
            ]
        )
        for row in rows:
            growth = rng.uniform(1.02, 1.09)
            writer.writerow(
                [
                    row["pn"],
                    row["sn"],
                    row["eo"],
                    int(row["hours"] * growth),
                    int(row["cycles"] * growth),
                    int(row["days"] * growth),
                    today.strftime("%Y-%m-%d"),
                    (today - timedelta(days=rng.randrange(0, 3))).strftime("%Y-%m-%d"),
                ]
            )
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="overwrite existing sample files"
    )
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_directories()
    configs = build_qvd_config(settings)

    writers = {
        ENGINEERING_ORDER: write_engineering_order,
        HARD_TIME_LIMIT: write_hard_time_limit,
        ACTUAL_UTILIZATION: write_actual_utilization,
    }

    for name, writer in writers.items():
        path = Path(configs[name].path)
        if path.exists() and not args.force:
            print(f"skipped {path} (already exists, use --force to overwrite)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        count = writer(path)
        print(f"wrote {count} rows to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

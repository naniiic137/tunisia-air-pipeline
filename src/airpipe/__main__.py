"""python -m airpipe [--offline] : extract -> load -> transform -> quality checks -> dashboard."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from . import dashboard
from .extract import CITIES, extract
from .load import load
from .quality import run_checks
from .transform import transform

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "air.duckdb"
SITE = ROOT / "site"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="reuse the last raw download instead of calling the API")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    if args.offline:
        raw = {"air": RAW / "air.json", "weather": RAW / "weather.json"}
        print("extract: skipped (--offline)")
    else:
        raw = extract(RAW)
        print(f"extract: {', '.join(p.name for p in raw.values())}")

    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    counts = load(con, raw)
    print(f"load: {counts}")
    print(f"transform: {transform(con)}")

    results = run_checks(con, expected_cities=len(CITIES))
    for r in results:
        mark = "ok  " if r["passed"] else ("FAIL" if r["severity"] == "error" else "warn")
        print(f"  [{mark}] {r['check']}" + ("" if r["passed"] else f" ({r['failing_rows']} rows)"))
    if any(not r["passed"] and r["severity"] == "error" for r in results):
        print("quality checks failed: nothing published")
        return 1

    dashboard.build(con, SITE / "index.html", results, started)
    (SITE / "summary.json").write_text(json.dumps(dashboard.summary(con), indent=2, default=str), encoding="utf-8")
    print(f"published: {SITE / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

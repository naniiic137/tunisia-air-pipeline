"""Data quality checks, run after every transform.

Each check is a SQL query that returns the offending rows (empty = pass). 'error' checks
stop the pipeline before anything is published; 'warn' checks are only reported.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb


@dataclass(frozen=True)
class Check:
    name: str
    severity: str  # "error" or "warn"
    sql: str


def checks(expected_cities: int, today: date | None = None) -> list[Check]:
    today = today or date.today()
    stale = today - timedelta(days=3)
    return [
        Check("every city has air quality data", "error",
              f"SELECT count(DISTINCT city) AS n FROM raw_air HAVING count(DISTINCT city) <> {expected_cities}"),
        Check("every city has weather data", "error",
              f"SELECT count(DISTINCT city) AS n FROM raw_weather HAVING count(DISTINCT city) <> {expected_cities}"),
        Check("one row per city and hour", "error",
              "SELECT city, ts, count(*) FROM stg_hourly GROUP BY city, ts HAVING count(*) > 1"),
        Check("pollutant values are physically plausible (0 to 2000 ug/m3)", "error",
              "SELECT city, ts FROM stg_hourly WHERE pm2_5 < 0 OR pm10 < 0 OR no2 < 0 OR o3 < 0 "
              "OR pm2_5 > 2000 OR pm10 > 2000"),
        Check("PM2.5 never exceeds PM10 by more than rounding", "warn",
              "SELECT city, ts FROM stg_hourly WHERE pm2_5 > pm10 + 1"),
        Check("each city has at least 90% of hourly PM2.5 values", "error",
              "SELECT city FROM stg_hourly GROUP BY city HAVING count(pm2_5) < 0.9 * count(*)"),
        Check("data is fresh (latest day within 3 days)", "error",
              f"SELECT max(day) FROM stg_hourly HAVING max(day) < DATE '{stale.isoformat()}'"),
        Check("complete days have 24 hours", "warn",
              "SELECT city, day, hours FROM daily WHERE hours NOT IN (0, 24) "
              "AND day > (SELECT min(day) FROM daily)"),
    ]


def run_checks(con: duckdb.DuckDBPyConnection, expected_cities: int, today: date | None = None) -> list[dict]:
    results = []
    for c in checks(expected_cities, today):
        bad = con.execute(c.sql).fetchall()
        results.append({"check": c.name, "severity": c.severity, "passed": not bad, "failing_rows": len(bad)})
    return results

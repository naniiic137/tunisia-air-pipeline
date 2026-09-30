"""Load: flatten the raw Open-Meteo JSON into long 'raw_*' tables in DuckDB.

The API returns one object per city, each with parallel hourly arrays. We store them in a
long format (city, time, variable, value) so adding a variable never changes a schema.
"""
from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import duckdb

from .extract import CITIES, City


def flatten(payload: list | dict, cities: list[City] = CITIES) -> list[tuple]:
    """Turns an API response into (city, ts, variable, value) rows. Responses come back in
    the same order as the requested coordinates, which is what ties them to city names."""
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(cities):
        raise ValueError(f"expected {len(cities)} locations in the response, got {len(items)}")
    rows = []
    for city, item in zip(cities, items, strict=True):
        hourly = item["hourly"]
        times = hourly["time"]
        for var, values in hourly.items():
            if var == "time":
                continue
            if len(values) != len(times):
                raise ValueError(f"{city.name}/{var}: {len(values)} values for {len(times)} timestamps")
            rows.extend((city.name, t, var, v) for t, v in zip(times, values, strict=True))
    return rows


def load(con: duckdb.DuckDBPyConnection, raw_files: dict[str, Path], cities: list[City] = CITIES) -> dict[str, int]:
    counts = {}
    con.execute("CREATE OR REPLACE TABLE cities (city VARCHAR PRIMARY KEY, lat DOUBLE, lon DOUBLE, note VARCHAR)")
    con.executemany("INSERT INTO cities VALUES (?, ?, ?, ?)", [(c.name, c.lat, c.lon, c.note) for c in cities])
    for name, path in raw_files.items():
        rows = flatten(json.loads(path.read_text(encoding="utf-8")), cities)
        table = f"raw_{name}"
        con.execute(f"CREATE OR REPLACE TABLE {table} (city VARCHAR, ts VARCHAR, variable VARCHAR, value DOUBLE)")
        if rows:
            # bulk load through a temporary CSV: binding rows from Python (executemany or list
            # parameters) takes minutes for ~130k rows, COPY takes well under a second
            with tempfile.TemporaryDirectory() as tmp:
                csv_path = Path(tmp) / f"{table}.csv"
                with csv_path.open("w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(rows)
                con.execute(f"COPY {table} FROM '{csv_path.as_posix()}' (HEADER false, NULLSTR '')")
        counts[table] = len(rows)
    return counts

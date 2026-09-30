"""Transform: run the SQL models in sql/ in filename order."""
from __future__ import annotations

from pathlib import Path

import duckdb

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def transform(con: duckdb.DuckDBPyConnection, sql_dir: Path = SQL_DIR) -> list[str]:
    ran = []
    for path in sorted(sql_dir.glob("*.sql")):
        con.execute(path.read_text(encoding="utf-8"))
        ran.append(path.name)
    return ran

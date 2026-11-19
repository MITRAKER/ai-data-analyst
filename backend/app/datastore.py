"""The datastore: where uploaded CSVs live and where SQL runs.

We use DuckDB, an in-process analytical database (think "SQLite for analytics").
It runs inside our Python process, so there is no database server to set up,
and it is very fast at the GROUP BY / aggregate queries a data analyst writes.

Safety model (important, because later an LLM will write the SQL):
1. DuckDB is opened with `enable_external_access=False`, so SQL cannot read or
   write files on disk (no `read_csv('/etc/passwd')`, no `COPY ... TO`).
   `lock_configuration=True` stops SQL from switching that setting back on.
2. `run_query` only accepts a single read-only statement (see sql_guard.py).
3. Results are capped at `max_rows`, so one query can't return millions of rows.
"""

from __future__ import annotations

import io
import re
import threading
from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from .sql_guard import UnsafeSQLError, ensure_read_only

MAX_UPLOAD_ROWS = 1_000_000


class DatasetError(ValueError):
    """Raised when a dataset can't be loaded or found."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
        }


def to_table_name(filename: str) -> str:
    """Turn 'Sales Report 2024.csv' into a safe SQL identifier: 'sales_report_2024'."""
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    name = re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_").lower()
    if not name:
        name = "dataset"
    if name[0].isdigit():
        name = f"t_{name}"
    return name[:63]


def _json_safe(df: pd.DataFrame) -> list[list[Any]]:
    """Convert a DataFrame into plain JSON-friendly lists (dates -> ISO strings, NaN -> None)."""
    import json

    payload = json.loads(df.to_json(orient="split", date_format="iso", index=False))
    return payload["data"]


class DataStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._con = duckdb.connect(
            path,
            config={"enable_external_access": False, "lock_configuration": True},
        )
        # One DuckDB connection shared across web requests: a lock keeps
        # concurrent requests from stepping on each other.
        self._lock = threading.Lock()

    # ---------- loading data ----------

    def load_csv(self, filename: str, content: bytes) -> dict[str, Any]:
        """Parse CSV bytes with pandas and store them as a DuckDB table."""
        if not content.strip():
            raise DatasetError("The file is empty.")
        try:
            df = pd.read_csv(io.BytesIO(content), nrows=MAX_UPLOAD_ROWS + 1)
        except Exception as exc:  # pandas raises many different error types
            raise DatasetError(f"Could not parse CSV: {exc}") from exc
        if len(df) > MAX_UPLOAD_ROWS:
            raise DatasetError(f"CSV has more than {MAX_UPLOAD_ROWS:,} rows.")
        if df.columns.empty:
            raise DatasetError("The CSV has no columns.")

        # Clean column names so they are easy to use in SQL (no spaces/odd chars).
        df.columns = _dedupe([to_table_name(str(c)) or "column" for c in df.columns])
        df = _parse_date_columns(df)

        table = to_table_name(filename)
        with self._lock:
            self._con.register("_upload", df)
            try:
                self._con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM _upload')
            finally:
                self._con.unregister("_upload")
        return self.describe(table)

    # ---------- inspecting data ----------

    def list_tables(self) -> list[str]:
        with self._lock:
            rows = self._con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        return [r[0] for r in rows]

    def describe(self, table: str, sample_rows: int = 5) -> dict[str, Any]:
        """Schema + row count + a few sample rows. This is exactly what we'll show
        the LLM later so it knows which columns exist before writing SQL."""
        if table not in self.list_tables():
            raise DatasetError(f"Unknown dataset: {table}")
        with self._lock:
            cols = self._con.execute(f'DESCRIBE "{table}"').fetchall()
            count = self._con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            sample = self._con.execute(f'SELECT * FROM "{table}" LIMIT {int(sample_rows)}').fetchdf()
        return {
            "name": table,
            "row_count": count,
            "columns": [{"name": c[0], "type": c[1]} for c in cols],
            "sample": _json_safe(sample),
        }

    # ---------- querying ----------

    def query_df(self, sql: str, max_rows: int = 200) -> tuple[pd.DataFrame, bool]:
        """Run read-only SQL and return (DataFrame, truncated)."""
        sql = ensure_read_only(sql)
        # Ask for one extra row so we can tell the caller the result was cut off.
        wrapped = f"SELECT * FROM ({sql}) AS _q LIMIT {int(max_rows) + 1}"
        with self._lock:
            try:
                df = self._con.execute(wrapped).fetchdf()
            except duckdb.Error as exc:
                # Return the database's own message: the agent will read it and fix its SQL.
                raise UnsafeSQLError(f"SQL error: {exc}") from exc
        truncated = len(df) > max_rows
        return df.head(max_rows), truncated

    def run_query(self, sql: str, max_rows: int = 200) -> QueryResult:
        df, truncated = self.query_df(sql, max_rows)
        return QueryResult(
            columns=[str(c) for c in df.columns],
            rows=_json_safe(df),
            row_count=len(df),
            truncated=truncated,
        )


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def _parse_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """pandas reads dates as text. If a text column looks like dates, convert it,
    so SQL like `date_trunc('month', order_date)` works."""
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            sample = df[col].dropna().astype(str).head(50)
            if sample.empty or not sample.str.match(r"^\d{4}-\d{2}-\d{2}").all():
                continue
            try:
                df[col] = pd.to_datetime(df[col], errors="raise")
            except (ValueError, TypeError):
                pass
    return df

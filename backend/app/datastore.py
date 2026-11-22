"""The datastore: where uploaded CSVs live and where SQL runs.

We use DuckDB, an in-process analytical database (think "SQLite for analytics").
It runs inside our Python process, so there is no database server to set up,
and it is very fast at the GROUP BY / aggregate queries a data analyst writes.

Safety model (important, because an AI model writes some of the SQL):
1. DuckDB is opened with `enable_external_access=False`, so SQL cannot read or
   write files on disk (no `read_csv('/etc/passwd')`, no `COPY ... TO`).
   `lock_configuration=True` stops SQL from switching that setting back on.
2. Only a single read-only statement is accepted (see sql_guard.py).
3. Every resource has a limit (Power of Ten rule 3): file size, rows, columns,
   tables, result rows, DuckDB's memory, and the time a query may run.
"""

from __future__ import annotations

import io
import json
import re
import threading
from collections.abc import Sequence
from typing import Final, NotRequired, TypedDict, override

import duckdb
import pandas as pd

from app.invariants import require
from app.sql_guard import UnsafeSQLError, ensure_read_only
from app.watchdog import Watchdog

MAX_UPLOAD_BYTES: Final = 50 * 1024 * 1024
MAX_UPLOAD_ROWS: Final = 1_000_000
MAX_COLUMNS: Final = 1_000
MAX_TABLES: Final = 50
MAX_RESULT_ROWS: Final = 200_000
MAX_SAMPLE_ROWS: Final = 20
QUERY_TIMEOUT_S: Final = 30.0
MEMORY_LIMIT: Final = "2GB"
DATE_SNIFF_ROWS: Final = 50

_IDENTIFIER: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")
_NOT_IDENTIFIER_CHARS: Final = re.compile(r"[^a-z0-9]+")
_ISO_DATE_START: Final = r"\d{4}-\d{2}-\d{2}"


class DatasetError(ValueError):
    """Raised when a dataset can't be loaded or found."""


class ColumnInfo(TypedDict):
    """One column of a dataset."""

    name: str
    type: str


class DatasetInfo(TypedDict):
    """What we know about a dataset: its schema, size and a few sample rows."""

    name: str
    row_count: int
    columns: list[ColumnInfo]
    sample: list[list[object]]


class QueryPayload(TypedDict):
    """A query result in a JSON-ready shape."""

    columns: list[str]
    rows: list[list[object]]
    row_count: int
    truncated: bool
    note: NotRequired[str]


def to_identifier(text: str, fallback: str) -> str:
    """Turn any text into a safe SQL identifier: 'Sales Report 2024' -> 'sales_report_2024'.

    Args:
        text: A file name, column header or similar.
        fallback: The name to use when nothing usable is left after cleaning.

    Returns:
        Lowercase letters, digits and underscores, at most 63 characters,
        never starting with a digit.
    """
    name = _NOT_IDENTIFIER_CHARS.sub("_", text.lower()).strip("_") or fallback
    if name[0].isdigit():
        name = f"t_{name}"
    name = name[:63]
    require(_IDENTIFIER.fullmatch(name) is not None, f"not a safe identifier: {name!r}")
    return name


def to_table_name(filename: str) -> str:
    """Turn 'Sales Report 2024.csv' into a safe table name: 'sales_report_2024'."""
    stem = filename.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return to_identifier(stem, "dataset")


def quote_identifier(name: str) -> str:
    """Wrap a table name in double quotes after checking it is a safe identifier."""
    require(_IDENTIFIER.fullmatch(name) is not None, f"unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def unique_names(names: Sequence[str]) -> list[str]:
    """Make every name unique by adding _1, _2, ... to repeats.

    ["a", "a", "a_1"] becomes ["a", "a_2", "a_1"]: a new name never collides
    with a name that is already in the list.
    """
    taken = set(names)
    result: list[str] = []
    used: set[str] = set()
    for name in names:
        candidate = name
        # n + 1 candidates and at most n taken names, so this always finds one.
        for suffix in range(1, len(names) + 2):
            if candidate not in used and (candidate == name or candidate not in taken):
                break
            candidate = f"{name[:58]}_{suffix}"
        require(candidate not in used, f"could not make {name!r} unique")
        used.add(candidate)
        result.append(candidate)
    return result


def records(df: pd.DataFrame) -> list[list[object]]:
    """Rows as JSON-safe lists: dates become ISO strings and NaN becomes None."""
    payload = json.loads(df.to_json(orient="split", date_format="iso", index=False))
    if not isinstance(payload, dict):
        raise TypeError("pandas returned unexpected JSON")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise TypeError("pandas returned unexpected JSON")
    return [list(row) for row in rows]


def parse_csv(content: bytes) -> pd.DataFrame:
    """Parse CSV bytes into a DataFrame with clean column names and real dates.

    Raises:
        DatasetError: If the file is empty, too big or not valid CSV.
    """
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetError(f"The file is larger than {MAX_UPLOAD_BYTES // 2**20} MB.")
    if not content.strip():
        raise DatasetError("The file is empty.")
    try:
        df = pd.read_csv(io.BytesIO(content), nrows=MAX_UPLOAD_ROWS + 1, low_memory=False)
    except ValueError as exc:  # pandas' parse and decode errors are all ValueErrors
        raise DatasetError(f"Could not parse CSV: {exc}") from exc
    if len(df) > MAX_UPLOAD_ROWS:
        raise DatasetError(f"The CSV has more than {MAX_UPLOAD_ROWS:,} rows.")
    if len(df.columns) > MAX_COLUMNS:
        raise DatasetError(f"The CSV has more than {MAX_COLUMNS:,} columns.")
    # Clean column names so they are easy to use in SQL (no spaces or odd characters).
    df.columns = pd.Index(unique_names([to_identifier(str(c), "column") for c in df.columns]))
    return parse_date_columns(df)


def parse_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert text columns that hold ISO dates (2025-01-31) into real dates.

    pandas reads dates as text. Converting them lets SQL such as
    `date_trunc('month', order_date)` work. A column is converted only if
    every value parses; otherwise it stays text.
    """
    for col in df.columns:
        series = df[col]
        if not (pd.api.types.is_string_dtype(series) or pd.api.types.is_object_dtype(series)):
            continue
        present = series.dropna()
        sample = present.astype(str).head(DATE_SNIFF_ROWS)
        if sample.empty or not sample.str.match(_ISO_DATE_START).all():
            continue
        parsed = pd.to_datetime(series, errors="coerce", format="ISO8601")
        if int(parsed.notna().sum()) == len(present):
            df[col] = parsed
    return df


class QueryWatchdog(Watchdog):
    """Interrupts a DuckDB query that runs longer than a time limit.

    DuckDB has no statement timeout of its own, so we add one.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection, timeout_s: float) -> None:
        super().__init__(name="duckdb-watchdog", timeout_s=timeout_s)
        self._con = con

    @override
    def on_timeout(self) -> None:
        self._con.interrupt()


class DataStore:
    """Holds the uploaded datasets in DuckDB and runs read-only SQL on them."""

    def __init__(
        self,
        path: str = ":memory:",
        memory_limit: str = MEMORY_LIMIT,
        query_timeout_s: float = QUERY_TIMEOUT_S,
    ) -> None:
        require(query_timeout_s > 0, "query_timeout_s must be positive")
        self._con = duckdb.connect(
            path,
            config={
                "enable_external_access": False,
                "lock_configuration": True,
                "memory_limit": memory_limit,
            },
        )
        # One DuckDB connection shared across web requests: a lock keeps
        # concurrent requests from stepping on each other.
        self._lock = threading.Lock()
        self._timeout_s = query_timeout_s

    def load_csv(self, filename: str, content: bytes) -> DatasetInfo:
        """Parse CSV bytes and store them as a table named after the file.

        Raises:
            DatasetError: If the file is empty, too big, not valid CSV, or
                there are already too many datasets.
        """
        df = parse_csv(content)
        table = to_table_name(filename)
        existing = self.list_tables()
        if table not in existing and len(existing) >= MAX_TABLES:
            raise DatasetError(f"There are already {MAX_TABLES} datasets. Restart to clear them.")
        target = quote_identifier(table)
        create = f"CREATE OR REPLACE TABLE {target} AS SELECT * FROM _upload"  # noqa: S608 -- target passed quote_identifier()
        with self._lock:
            _ = self._con.register("_upload", df)
            try:
                _ = self._con.execute(create)
            finally:
                _ = self._con.unregister("_upload")
        return self.describe(table)

    def list_tables(self) -> list[str]:
        """Names of all datasets, in alphabetical order."""
        with self._lock:
            rows = self._con.sql(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def describe(self, table: str, sample_rows: int = 5) -> DatasetInfo:
        """Schema, row count and a few sample rows.

        This is exactly what the AI model sees before it writes SQL.

        Raises:
            DatasetError: If there is no dataset with that name.
        """
        require(0 <= sample_rows <= MAX_SAMPLE_ROWS, f"sample_rows out of range: {sample_rows}")
        if table not in self.list_tables():
            raise DatasetError(f"Unknown dataset: {table}")
        with self._lock:
            relation = self._con.table(quote_identifier(table))
            columns = [
                ColumnInfo(name=name, type=str(kind))
                for name, kind in zip(relation.columns, relation.types, strict=True)
            ]
            counts = relation.aggregate("count(*)").fetchall()
            sample = relation.limit(sample_rows).df()
        require(len(counts) == 1, "count(*) must return one row")
        row_count = counts[0][0]
        require(isinstance(row_count, int), "count(*) must return an integer")
        return DatasetInfo(
            name=table, row_count=int(row_count), columns=columns, sample=records(sample)
        )

    def query_df(self, sql: str, max_rows: int) -> tuple[pd.DataFrame, bool]:
        """Run one read-only SELECT and return (rows, truncated).

        Raises:
            UnsafeSQLError: If the SQL is not a single SELECT, fails, or runs
                longer than the time limit.
        """
        require(0 < max_rows <= MAX_RESULT_ROWS, f"max_rows out of range: {max_rows}")
        cleaned = ensure_read_only(sql)
        with self._lock:
            watchdog = QueryWatchdog(self._con, self._timeout_s)
            watchdog.start()
            try:
                # Ask for one extra row so we can tell the caller the result was cut off.
                df = self._con.sql(cleaned).limit(max_rows + 1).df()
            except duckdb.InterruptException as exc:
                raise UnsafeSQLError(
                    f"The query ran longer than {self._timeout_s:.0f} seconds and was stopped. "
                    "Filter or aggregate more, and avoid joins that multiply rows."
                ) from exc
            except duckdb.Error as exc:
                # Return the database's own message: the agent reads it and fixes its SQL.
                raise UnsafeSQLError(f"SQL error: {exc}") from exc
            finally:
                _ = watchdog.finish()
        return df.head(max_rows), len(df) > max_rows

    def run_query(self, sql: str, max_rows: int) -> QueryPayload:
        """Run one read-only SELECT and return the result in a JSON-ready shape."""
        df, truncated = self.query_df(sql, max_rows)
        return QueryPayload(
            columns=[str(c) for c in df.columns],
            rows=records(df),
            row_count=len(df),
            truncated=truncated,
        )

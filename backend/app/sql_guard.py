"""A guard that only lets read-only SQL through.

Why not just check `sql.lower().startswith("select")`? Because text checks are
easy to fool: "select 1; drop table sales" starts with "select". Instead we ask
DuckDB's own parser to split the text into statements and tell us each one's
type. The database knows its grammar better than any regex we could write.
"""

from __future__ import annotations

import duckdb

ALLOWED = {duckdb.StatementType.SELECT}


class UnsafeSQLError(ValueError):
    """Raised for SQL we refuse to run, or SQL the database rejected."""


def ensure_read_only(sql: str) -> str:
    """Return the cleaned SQL if it is exactly one SELECT statement, else raise."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise UnsafeSQLError("Empty SQL.")
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as exc:
        raise UnsafeSQLError(f"SQL could not be parsed: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeSQLError("Only one SQL statement is allowed at a time.")
    if statements[0].type not in ALLOWED:
        raise UnsafeSQLError(
            f"Only read-only SELECT queries are allowed (got {statements[0].type.name})."
        )
    return sql

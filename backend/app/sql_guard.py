"""A guard that only lets read-only SQL through.

Why not just check `sql.lower().startswith("select")`? Because text checks are
easy to fool: "select 1; drop table sales" starts with "select". Instead we ask
DuckDB's own parser to split the text into statements and tell us each one's
type. The database knows its grammar better than any regex we could write.
"""

from __future__ import annotations

from typing import Final

import duckdb

ALLOWED: Final = frozenset({duckdb.StatementType.SELECT})
MAX_SQL_CHARS: Final = 20_000  # far longer than any useful query


class UnsafeSQLError(ValueError):
    """Raised for SQL we refuse to run, or SQL the database rejected."""


def ensure_read_only(sql: str) -> str:
    """Check that `sql` is exactly one SELECT statement.

    Args:
        sql: SQL text from a user or from the AI model.

    Returns:
        The SQL with surrounding whitespace and trailing semicolons removed.

    Raises:
        UnsafeSQLError: If the SQL is empty, too long, unparsable, more than one
            statement, or not a SELECT.
    """
    if len(sql) > MAX_SQL_CHARS:
        raise UnsafeSQLError(f"SQL is longer than {MAX_SQL_CHARS:,} characters.")
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQLError("Empty SQL.")
    try:
        statements = duckdb.extract_statements(cleaned)
    except duckdb.Error as exc:
        raise UnsafeSQLError(f"SQL could not be parsed: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeSQLError("Only one SQL statement is allowed at a time.")
    kind = statements[0].type
    if kind not in ALLOWED:
        raise UnsafeSQLError(f"Only read-only SELECT queries are allowed (got {kind.name}).")
    return cleaned

"""Tests for the datastore, the SQL guard and the .env loader."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from app.config import load_dotenv, parse_dotenv
from app.datastore import (
    MAX_TABLES,
    DatasetError,
    DataStore,
    parse_csv,
    quote_identifier,
    records,
    to_identifier,
    to_table_name,
    unique_names,
)
from app.files import read_capped
from app.invariants import InvariantError
from app.sql_guard import MAX_SQL_CHARS, UnsafeSQLError, ensure_read_only

# ---------- names ----------


def test_table_name() -> None:
    assert to_table_name("2024 Sales.csv") == "t_2024_sales"
    assert to_table_name("???.csv") == "dataset"
    assert to_table_name("C:\\data\\Orders.CSV") == "orders"
    assert len(to_table_name("x" * 100 + ".csv")) == 63


def test_identifier_fallback() -> None:
    assert to_identifier("  ", "column") == "column"
    assert to_identifier("Total $", "column") == "total"


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["a", "b"], ["a", "b"]),
        (["a", "a", "a"], ["a", "a_1", "a_2"]),
        (["a", "a", "a_1"], ["a", "a_2", "a_1"]),
        (["a_1", "a", "a"], ["a_1", "a", "a_2"]),
    ],
)
def test_unique_names(names: list[str], expected: list[str]) -> None:
    assert unique_names(names) == expected


def test_quote_identifier_rejects_unsafe_names() -> None:
    assert quote_identifier("sales") == '"sales"'
    with pytest.raises(InvariantError):
        _ = quote_identifier('x"; DROP TABLE sales; --')


# ---------- parsing ----------


def test_records_are_json_safe() -> None:
    df = pd.DataFrame({"d": pd.to_datetime(["2025-01-02"]), "v": [float("nan")]})
    assert records(df) == [["2025-01-02T00:00:00.000", None]]


def test_dates_are_parsed_only_when_every_value_is_a_date() -> None:
    df = parse_csv(
        b"good,mixed,invalid,num\n2025-01-01,2025-01-01,2025-01-01,1\n2025-02-01,soon,2025-13-45,2\n"
    )
    assert pd.api.types.is_datetime64_any_dtype(df["good"])
    assert not pd.api.types.is_datetime64_any_dtype(df["mixed"])
    assert not pd.api.types.is_datetime64_any_dtype(df["invalid"])
    assert not pd.api.types.is_datetime64_any_dtype(df["num"])


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"   \n", "empty"),
        (b'a,b\n"1,2\n', "Could not parse"),
    ],
)
def test_bad_csv(content: bytes, message: str) -> None:
    with pytest.raises(DatasetError, match=message):
        _ = parse_csv(content)


def test_csv_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.datastore.MAX_UPLOAD_ROWS", 2)
    with pytest.raises(DatasetError, match="more than 2 rows"):
        _ = parse_csv(b"a\n1\n2\n3\n")
    monkeypatch.setattr("app.datastore.MAX_COLUMNS", 2)
    with pytest.raises(DatasetError, match="more than 2 columns"):
        _ = parse_csv(b"a,b,c\n1,2,3\n")
    monkeypatch.setattr("app.datastore.MAX_UPLOAD_BYTES", 5)
    with pytest.raises(DatasetError, match="larger than"):
        _ = parse_csv(b"a,b,c\n1,2,3\n")


# ---------- the store ----------


def test_load_and_describe(store: DataStore) -> None:
    info = store.describe("sales", sample_rows=2)
    assert info["row_count"] == 2000
    assert len(info["sample"]) == 2
    with pytest.raises(DatasetError):
        _ = store.describe("nope")
    with pytest.raises(InvariantError):
        _ = store.describe("sales", sample_rows=1000)


def test_reloading_a_file_replaces_the_table(store: DataStore) -> None:
    info = store.load_csv("sales.csv", b"a\n1\n")
    assert info["row_count"] == 1
    assert store.list_tables() == ["sales"]


def test_table_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.datastore.MAX_TABLES", 1)
    fresh = DataStore()
    _ = fresh.load_csv("one.csv", b"a\n1\n")
    _ = fresh.load_csv("one.csv", b"a\n2\n")  # replacing an existing table is fine
    with pytest.raises(DatasetError, match="already 1 datasets"):
        _ = fresh.load_csv("two.csv", b"a\n1\n")
    assert MAX_TABLES > 1


def test_query_df_limits(store: DataStore) -> None:
    df, truncated = store.query_df("SELECT * FROM sales", max_rows=3)
    assert (len(df), truncated) == (3, True)
    with pytest.raises(InvariantError):
        _ = store.query_df("SELECT 1", max_rows=0)


def test_slow_queries_are_stopped() -> None:
    fresh = DataStore(query_timeout_s=0.5)
    with pytest.raises(UnsafeSQLError, match="longer than"):
        _ = fresh.query_df("SELECT count(*) FROM range(100000000000)", max_rows=1)
    # The connection still works afterwards.
    df, _truncated = fresh.query_df("SELECT 42 AS answer", max_rows=1)
    assert int(df["answer"].iloc[0]) == 42


def test_store_needs_a_positive_timeout() -> None:
    with pytest.raises(InvariantError):
        _ = DataStore(query_timeout_s=0)


# ---------- the SQL guard ----------


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "SELECT 1; DROP TABLE sales",
        "DELETE FROM sales",
        "INSERT INTO sales VALUES (1)",
        "COPY sales TO 'out.csv'",
        "ATTACH 'other.db'",
        "PRAGMA database_list",
        "SET memory_limit = '10GB'",
        "",
        " ; ",
        "SELEC 1",
        "x" * (MAX_SQL_CHARS + 1),
    ],
)
def test_guard_rejects_unsafe_sql(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        _ = ensure_read_only(sql)


def test_guard_cleans_safe_sql() -> None:
    assert ensure_read_only("  SELECT 1;  ") == "SELECT 1"


# ---------- .env loading ----------


def test_parse_dotenv() -> None:
    text = "# comment\n\nA=1\nB = 'two'\nC=\"three\"\nEMPTY=\nNOEQUALS\n=nokey\n"
    assert parse_dotenv(text) == {"A": "1", "B": "two", "C": "three"}


def test_load_dotenv_keeps_real_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    _ = env_file.write_text("DOTENV_TEST_A=from-file\nDOTENV_TEST_B=from-file\n", encoding="utf-8")
    monkeypatch.setenv("DOTENV_TEST_A", "from-env")
    monkeypatch.delenv("DOTENV_TEST_B", raising=False)
    load_dotenv((env_file, tmp_path / "missing.env"))
    assert os.environ["DOTENV_TEST_A"] == "from-env"
    assert os.environ["DOTENV_TEST_B"] == "from-file"
    monkeypatch.delenv("DOTENV_TEST_B")


def test_load_dotenv_ignores_huge_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    _ = env_file.write_text("DOTENV_TEST_C=1\n" + "#" * 70_000, encoding="utf-8")
    monkeypatch.delenv("DOTENV_TEST_C", raising=False)
    load_dotenv((env_file,))
    assert "DOTENV_TEST_C" not in os.environ


def test_load_dotenv_default_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _ = (tmp_path / ".env").write_text("DOTENV_TEST_D=yes\n", encoding="utf-8")
    monkeypatch.delenv("DOTENV_TEST_D", raising=False)
    load_dotenv()
    assert os.environ["DOTENV_TEST_D"] == "yes"
    monkeypatch.delenv("DOTENV_TEST_D")


# ---------- bounded file reads ----------


def test_read_capped(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    _ = path.write_bytes(b"12345")
    assert read_capped(path, 5) == b"12345"
    assert read_capped(path, 4) is None
    with pytest.raises(InvariantError):
        _ = read_capped(path, 0)

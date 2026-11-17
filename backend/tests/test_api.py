from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.datastore import DataStore, to_table_name
from app.main import create_app
from app.sql_guard import UnsafeSQLError, ensure_read_only

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample_sales.csv"


@pytest.fixture
def client() -> TestClient:
    # Each test gets a fresh in-memory database, so tests can't affect each other.
    return TestClient(create_app(DataStore(":memory:")))


def upload(client: TestClient, name: str, content: bytes):
    return client.post("/datasets", files={"file": (name, content, "text/csv")})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_sample_and_describe(client):
    res = upload(client, "sample_sales.csv", SAMPLE.read_bytes())
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "sample_sales"
    assert body["row_count"] == 2000
    types = {c["name"]: c["type"] for c in body["columns"]}
    assert types["order_date"].startswith("TIMESTAMP")  # text dates were parsed
    assert types["revenue"] == "DOUBLE"
    assert len(body["sample"]) == 5

    assert client.get("/datasets").json() == {"datasets": ["sample_sales"]}
    assert client.get("/datasets/sample_sales").status_code == 200
    assert client.get("/datasets/nope").status_code == 404


def test_messy_column_names_are_cleaned(client):
    res = upload(client, "My Data (v2).csv", b"Order ID,Total $,Total $\n1,10,11\n")
    body = res.json()
    assert body["name"] == "my_data_v2"
    assert [c["name"] for c in body["columns"]] == ["order_id", "total", "total_1"]


def test_query_aggregates(client):
    upload(client, "sales.csv", SAMPLE.read_bytes())
    res = client.post(
        "/query",
        json={"sql": "SELECT region, ROUND(SUM(revenue), 2) AS total FROM sales GROUP BY 1 ORDER BY 1"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["columns"] == ["region", "total"]
    assert [r[0] for r in body["rows"]] == ["East", "North", "South", "West"]
    assert body["truncated"] is False


def test_query_truncates_large_results(client):
    upload(client, "sales.csv", SAMPLE.read_bytes())
    body = client.post("/query", json={"sql": "SELECT * FROM sales", "max_rows": 10}).json()
    assert body["row_count"] == 10
    assert body["truncated"] is True


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "SELECT 1; DROP TABLE sales",
        "DELETE FROM sales",
        "INSERT INTO sales VALUES (1)",
        "COPY sales TO 'out.csv'",
        "ATTACH 'other.db'",
        "",
    ],
)
def test_guard_rejects_unsafe_sql(sql):
    with pytest.raises(UnsafeSQLError):
        ensure_read_only(sql)


def test_select_cannot_read_files(client):
    # Even a valid SELECT can't touch the filesystem, because external access is off.
    res = client.post("/query", json={"sql": "SELECT * FROM read_csv('/etc/passwd')"})
    assert res.status_code == 400


def test_bad_sql_returns_helpful_error(client):
    upload(client, "sales.csv", SAMPLE.read_bytes())
    res = client.post("/query", json={"sql": "SELECT no_such_column FROM sales"})
    assert res.status_code == 400
    assert "no_such_column" in res.json()["detail"]


def test_rejects_non_csv_and_empty(client):
    assert upload(client, "x.txt", b"a\n1\n").status_code == 400
    assert upload(client, "x.csv", b"").status_code == 400


def test_table_name():
    assert to_table_name("2024 Sales.csv") == "t_2024_sales"
    assert to_table_name("???.csv") == "dataset"

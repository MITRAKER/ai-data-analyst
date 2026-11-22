"""Tests for the web API."""

from __future__ import annotations

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.agent.events import AgentEvent
from app.datastore import DataStore
from app.invariants import InvariantError
from app.main import create_app, llm_from_env, summarize
from tests.fakes import FakeLLM, reply, text, tool_use


@pytest.fixture
def client() -> TestClient:
    # Each test gets a fresh in-memory database, so tests can't affect each other.
    return TestClient(create_app(DataStore(":memory:"), FakeLLM([])))


def upload(client: TestClient, name: str, content: bytes) -> httpx2.Response:
    return client.post("/datasets", files={"file": (name, content, "text/csv")})


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_sample_and_describe(client: TestClient, sample_bytes: bytes) -> None:
    res = upload(client, "sample_sales.csv", sample_bytes)
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


def test_messy_column_names_are_cleaned(client: TestClient) -> None:
    res = upload(client, "My Data (v2).csv", b"Order ID,Total $,Total $,total_1\n1,10,11,12\n")
    body = res.json()
    assert body["name"] == "my_data_v2"
    # pandas renames the repeated header to "Total $.1"; cleaning makes it "total_1",
    # which collides with the real total_1 column, so that one gets a new name.
    assert [c["name"] for c in body["columns"]] == ["order_id", "total", "total_1", "total_1_1"]


def test_query_aggregates(client: TestClient, sample_bytes: bytes) -> None:
    _ = upload(client, "sales.csv", sample_bytes)
    res = client.post(
        "/query",
        json={
            "sql": "SELECT region, ROUND(SUM(revenue), 2) AS total FROM sales GROUP BY 1 ORDER BY 1"
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["columns"] == ["region", "total"]
    assert [r[0] for r in body["rows"]] == ["East", "North", "South", "West"]
    assert body["truncated"] is False


def test_query_truncates_large_results(client: TestClient, sample_bytes: bytes) -> None:
    _ = upload(client, "sales.csv", sample_bytes)
    body = client.post("/query", json={"sql": "SELECT * FROM sales", "max_rows": 10}).json()
    assert body["row_count"] == 10
    assert body["truncated"] is True


@pytest.mark.parametrize("payload", [{"sql": "SELECT 1", "max_rows": 0}, {"sql": "x" * 20_001}])
def test_query_request_is_validated(client: TestClient, payload: dict[str, object]) -> None:
    assert client.post("/query", json=payload).status_code == 422


def test_select_cannot_read_files(client: TestClient) -> None:
    # Even a valid SELECT can't touch the filesystem, because external access is off.
    res = client.post("/query", json={"sql": "SELECT * FROM read_csv('/etc/passwd')"})
    assert res.status_code == 400


def test_bad_sql_returns_helpful_error(client: TestClient, sample_bytes: bytes) -> None:
    _ = upload(client, "sales.csv", sample_bytes)
    res = client.post("/query", json={"sql": "SELECT no_such_column FROM sales"})
    assert res.status_code == 400
    assert "no_such_column" in res.json()["detail"]


def test_rejects_non_csv_empty_and_broken_files(client: TestClient) -> None:
    assert upload(client, "x.txt", b"a\n1\n").status_code == 400
    assert upload(client, "x.csv", b"").status_code == 400
    assert upload(client, "x.csv", b'a,b\n"1,2\n').status_code == 400


def test_rejects_files_that_are_too_big(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 10)
    assert upload(client, "x.csv", b"a,b\n" + b"1,2\n" * 10).status_code == 413


# ---------- /ask ----------


def ask_client(llm: FakeLLM, sample_bytes: bytes) -> TestClient:
    api = TestClient(create_app(DataStore(":memory:"), llm))
    _ = upload(api, "sales.csv", sample_bytes)
    return api


def test_ask_returns_answer_and_steps(sample_bytes: bytes) -> None:
    llm = FakeLLM(
        [
            reply(
                tool_use("t1", "query_database", sql="SELECT COUNT(*) AS n FROM sales", purpose="")
            ),
            reply(text("2,000 orders."), stop="end_turn"),
        ]
    )
    body = ask_client(llm, sample_bytes).post("/ask", json={"question": "How many orders?"}).json()
    assert body["ok"] is True
    assert body["answer"] == "2,000 orders."
    assert body["charts"] == []
    assert [s["type"] for s in body["steps"]] == ["tool_call", "tool_result"]


def test_ask_reports_failure(sample_bytes: bytes) -> None:
    api = ask_client(FakeLLM([reply(stop="refusal")]), sample_bytes)
    body = api.post("/ask", json={"question": "anything?"}).json()
    assert body == {
        "ok": False,
        "answer": "The model declined to answer this request.",
        "charts": [],
        "steps": [],
    }


def test_ask_validates_datasets_and_question(sample_bytes: bytes) -> None:
    api = ask_client(FakeLLM([]), sample_bytes)
    assert api.post("/ask", json={"question": "hi?", "datasets": ["nope"]}).status_code == 404
    assert api.post("/ask", json={"question": "hi"}).status_code == 422


def test_ask_with_listed_datasets(sample_bytes: bytes) -> None:
    api = ask_client(FakeLLM([reply(text("ok"), stop="end_turn")]), sample_bytes)
    res = api.post("/ask", json={"question": "hi?", "datasets": ["sales"]})
    assert res.json()["ok"] is True


def test_ask_without_api_key_returns_503() -> None:
    api = TestClient(create_app(DataStore(":memory:")))  # the real client, but no key is set
    res = api.post("/ask", json={"question": "anything?"})
    assert res.status_code == 503
    assert "ANTHROPIC_API_KEY is not set" in res.json()["detail"]


def test_summarize_needs_a_final_event() -> None:
    with pytest.raises(InvariantError):
        _ = summarize([])
    note: AgentEvent = {"type": "note", "text": "hi"}
    with pytest.raises(InvariantError):
        _ = summarize([note])


def test_services_must_be_set_up() -> None:
    app = create_app(DataStore(":memory:"), FakeLLM([]))
    app.state.services = None
    with pytest.raises(InvariantError):
        _ = TestClient(app).get("/datasets")


def test_api_uses_the_real_client_when_a_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    llm, problem = llm_from_env()
    assert llm is not None
    assert problem == ""

"""Tests for the web API."""

from __future__ import annotations

import json

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.agent.events import AgentEvent
from app.datastore import DataStore
from app.invariants import InvariantError
from app.main import allowed_hosts, create_app, llm_from_env, summarize
from tests.fakes import FakeLLM, reply, text, tool_use


@pytest.fixture(autouse=True)
def allow_test_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """TestClient sends `Host: testserver`, and the API answers only to names it knows."""
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")


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


# ---------- requests that other websites could make a browser send ----------

CSV_FILE = {"file": ("x.csv", b"a\n1\n", "text/csv")}


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "https://evil.example"},
        {"origin": "http://testserver:3000"},  # the web UI's page, on another port
        {"origin": "null"},  # a page that hides where it comes from
        {"sec-fetch-site": "cross-site"},
        {"sec-fetch-site": "same-site"},
        {"sec-fetch-site": "none"},
    ],
)
def test_refuses_posts_from_other_websites(client: TestClient, headers: dict[str, str]) -> None:
    res = client.post("/datasets", files=CSV_FILE, headers=headers)
    assert res.status_code == 403
    assert res.json() == {"detail": "Requests from other websites are not allowed."}
    assert client.post("/ask", json={"question": "Who?"}, headers=headers).status_code == 403
    assert client.get("/datasets").json() == {"datasets": []}


def test_allows_the_docs_page_programs_and_reading(client: TestClient) -> None:
    # The interactive docs at /docs send same-origin requests; curl sends neither header.
    same_origin = {"origin": "http://testserver", "sec-fetch-site": "same-origin"}
    assert client.post("/datasets", files=CSV_FILE, headers=same_origin).status_code == 201
    assert client.post("/datasets", files=CSV_FILE).status_code == 201
    # Another website's page can't read an answer, so reading is allowed from anywhere.
    elsewhere = {"origin": "https://evil.example", "sec-fetch-site": "cross-site"}
    assert client.get("/datasets", headers=elsewhere).json() == {"datasets": ["x"]}


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:8000", "localhost.evil.example", "localhost:80:80", "[::2]", ""],
)
def test_refuses_host_names_it_doesnt_know(client: TestClient, host: str) -> None:
    res = client.get("/health", headers={"host": host})
    assert res.status_code == 421
    assert "add it to ALLOWED_HOSTS" in res.json()["detail"]
    assert client.post("/datasets", files=CSV_FILE, headers={"host": host}).status_code == 421


@pytest.mark.parametrize(
    "host", ["localhost", "localhost:8000", "LocalHost:8000", "127.0.0.1:8000", "[::1]:8000"]
)
def test_answers_to_this_computers_names(client: TestClient, host: str) -> None:
    assert client.get("/health", headers={"host": host}).status_code == 200


def test_answers_to_the_names_in_allowed_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", " Analyst.example, ,10.0.0.5 ")
    api = TestClient(create_app(DataStore(":memory:"), FakeLLM([])))
    for host in ["analyst.example", "analyst.example:8000", "10.0.0.5:8000", "localhost:8000"]:
        assert api.get("/health", headers={"host": host}).status_code == 200
    # "api" is the API's name inside Docker Compose, where the web UI's server calls it.
    assert api.get("/health", headers={"host": "api:8000"}).status_code == 200
    assert api.get("/health").status_code == 421  # testserver is no longer listed
    assert allowed_hosts("") == {"localhost", "127.0.0.1", "[::1]", "api"}


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
    # Spaces don't count: a question of only spaces is too short too.
    assert api.post("/ask", json={"question": "     "}).status_code == 422
    assert api.post("/ask", json={"question": "  hi  "}).status_code == 422


def test_ask_with_listed_datasets(sample_bytes: bytes) -> None:
    api = ask_client(FakeLLM([reply(text("ok"), stop="end_turn")]), sample_bytes)
    res = api.post("/ask", json={"question": "hi?", "datasets": ["sales"]})
    assert res.json()["ok"] is True


def test_ask_without_api_key_returns_503() -> None:
    api = TestClient(create_app(DataStore(":memory:")))  # the real client, but no key is set
    res = api.post("/ask", json={"question": "anything?"})
    assert res.status_code == 503
    assert "ANTHROPIC_API_KEY is not set" in res.json()["detail"]


def test_agent_status_says_whether_the_agent_can_answer() -> None:
    ready = TestClient(create_app(DataStore(":memory:"), FakeLLM([])))
    assert ready.get("/agent/status").json() == {"ready": True, "detail": ""}
    no_key = TestClient(create_app(DataStore(":memory:")))  # the real client, but no key
    status = no_key.get("/agent/status").json()
    assert status["ready"] is False
    assert "ANTHROPIC_API_KEY is not set" in status["detail"]


def sse_events(body: str) -> list[tuple[str, dict[str, object]]]:
    """Parse a text/event-stream body into (event name, data) pairs."""
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if not line.startswith(":")]
        if not lines:
            continue
        name = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = "\n".join(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


def test_ask_stream_sends_each_step_as_it_happens(sample_bytes: bytes) -> None:
    llm = FakeLLM(
        [
            reply(
                text("Let me count."),
                tool_use("t1", "query_database", sql="SELECT COUNT(*) AS n FROM sales", purpose=""),
            ),
            reply(text("2,000 orders."), stop="end_turn"),
        ]
    )
    res = ask_client(llm, sample_bytes).post("/ask/stream", json={"question": "How many?"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["cache-control"] == "no-cache"
    events = sse_events(res.text)
    assert [name for name, _ in events] == ["note", "tool_call", "tool_result", "answer"]
    # The event name is the event's type, and the data is the whole event.
    assert all(name == data["type"] for name, data in events)
    assert events[2][1]["display"] == {
        "result": {"columns": ["n"], "rows": [[2000]], "row_count": 1, "truncated": False}
    }
    assert events[-1][1] == {"type": "answer", "text": "2,000 orders.", "charts": [], "steps": 2}


def test_ask_stream_ends_with_an_error_event_when_the_run_fails(sample_bytes: bytes) -> None:
    api = ask_client(FakeLLM([reply(stop="refusal")]), sample_bytes)
    events = sse_events(api.post("/ask/stream", json={"question": "anything?"}).text)
    assert events == [
        (
            "error",
            {
                "type": "error",
                "message": "The model declined to answer this request.",
                "charts": [],
            },
        )
    ]


def test_ask_stream_ends_with_an_error_event_after_an_unexpected_failure(
    sample_bytes: bytes,
) -> None:
    # This fake has no replies left, so the agent's first call to it fails with
    # an IndexError: a stand-in for any bug that the agent does not expect.
    api = ask_client(FakeLLM([]), sample_bytes)
    events = sse_events(api.post("/ask/stream", json={"question": "How many?"}).text)
    assert events == [
        (
            "error",
            {
                "type": "error",
                "message": "The agent failed unexpectedly. Please try again.",
                "charts": [],
            },
        )
    ]


def test_ask_stream_checks_the_request_before_streaming(sample_bytes: bytes) -> None:
    # A request that can't succeed gets a plain HTTP error, never a stream.
    api = ask_client(FakeLLM([]), sample_bytes)
    unknown = api.post("/ask/stream", json={"question": "hi?", "datasets": ["nope"]})
    assert unknown.status_code == 404
    assert unknown.headers["content-type"] == "application/json"
    assert api.post("/ask/stream", json={"question": "hi"}).status_code == 422
    assert api.post("/ask/stream", json={"question": "     "}).status_code == 422
    no_key = TestClient(create_app(DataStore(":memory:")))
    res = no_key.post("/ask/stream", json={"question": "anything?"})
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

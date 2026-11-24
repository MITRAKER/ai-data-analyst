"""The web API (FastAPI).

Endpoints:
  GET  /health                     -> is the server up?
  POST /datasets                   -> upload a CSV, get its schema back
  GET  /datasets                   -> list uploaded datasets
  GET  /datasets/{name}            -> schema, row count and sample rows
  POST /query                      -> run one read-only SQL query
  GET  /agent/status               -> can the agent answer questions?
  POST /ask                        -> ask the AI agent a question
  POST /ask/stream                 -> the same, with each step sent as it happens

The agent calls the same DataStore methods as its "tools".

Browsers never call this API directly. The web UI's server forwards their
requests (see frontend/src/app/api/), so the API needs no CORS settings and
can stay on a private network.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, TypedDict

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from app import __version__
from app.agent.charts import Chart
from app.agent.events import AgentEvent
from app.agent.llm import AgentConfigError, LLMClient, claude_client_from_env
from app.agent.orchestrator import DataAnalystAgent
from app.config import load_dotenv
from app.datastore import MAX_UPLOAD_BYTES, DatasetError, DatasetInfo, DataStore, QueryPayload
from app.invariants import InvariantError
from app.sql_guard import MAX_SQL_CHARS, UnsafeSQLError

MAX_QUERY_ROWS = 5_000
MAX_QUESTION_CHARS = 2_000
MAX_DATASETS_PER_QUESTION = 50


class QueryRequest(BaseModel):
    """Pydantic validates the JSON body: wrong types or out-of-range values -> 422."""

    sql: str = Field(
        max_length=MAX_SQL_CHARS,
        examples=["SELECT region, SUM(revenue) FROM sales GROUP BY 1"],
    )
    max_rows: int = Field(200, ge=1, le=MAX_QUERY_ROWS)


class AskRequest(BaseModel):
    """A question for the agent, optionally limited to some datasets."""

    question: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)
    datasets: list[str] | None = Field(
        None,
        max_length=MAX_DATASETS_PER_QUESTION,
        description="Limit to these datasets (default: all).",
    )


class AskResponse(TypedDict):
    """The agent's answer, its charts and every step it took."""

    ok: bool
    answer: str
    charts: list[Chart]
    steps: list[AgentEvent]


class AgentStatus(TypedDict):
    """Whether the agent can answer questions, and if not, why."""

    ready: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Services:
    """What the routes need: the datastore and (if configured) the model client."""

    store: DataStore
    llm: LLMClient | None
    llm_problem: str = ""


router = APIRouter()


def services(request: Request) -> Services:
    """The Services object that create_app() stored on the app."""
    found = request.app.state.services
    if not isinstance(found, Services):
        raise InvariantError("create_app() must set app.state.services")
    return found


@router.get("/health")
def health() -> dict[str, str]:
    """Is the server up?"""
    return {"status": "ok"}


@router.post("/datasets", status_code=201)
def upload_dataset(request: Request, file: UploadFile) -> DatasetInfo:
    """Upload a CSV file and get its schema back."""
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file.")
    # Read at most one byte more than allowed: enough to know the file is too big.
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES // 2**20} MB.")
    try:
        return services(request).store.load_csv(filename, content)
    except DatasetError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/datasets")
def list_datasets(request: Request) -> dict[str, list[str]]:
    """List uploaded datasets."""
    return {"datasets": services(request).store.list_tables()}


@router.get("/datasets/{name}")
def get_dataset(name: str, request: Request) -> DatasetInfo:
    """Schema, row count and sample rows of one dataset."""
    try:
        return services(request).store.describe(name)
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/query")
def query(body: QueryRequest, request: Request) -> QueryPayload:
    """Run one read-only SQL query."""
    try:
        return services(request).store.run_query(body.sql, body.max_rows)
    except UnsafeSQLError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/agent/status")
def agent_status(request: Request) -> AgentStatus:
    """Can the agent answer questions? If not, `detail` says why."""
    found = services(request)
    if found.llm is None:
        return AgentStatus(ready=False, detail=found.llm_problem)
    return AgentStatus(ready=True, detail="")


class AgentRun:
    """A question that passed every check, ready for the agent to answer.

    /ask and /ask/stream declare `Annotated[AgentRun, Depends()]`, so FastAPI
    builds an AgentRun from the request before the endpoint runs. A question
    the agent can't answer gets a plain HTTP error here, and a stream never
    starts for it.
    """

    def __init__(self, body: AskRequest, request: Request) -> None:
        found = services(request)
        if found.llm is None:
            raise HTTPException(503, f"Agent unavailable: {found.llm_problem}")
        if body.datasets:
            unknown = sorted(set(body.datasets) - set(found.store.list_tables()))
            if unknown:
                raise HTTPException(404, f"Unknown dataset(s): {unknown}")
        self._agent = DataAnalystAgent(found.store, found.llm)
        self._question = body.question
        self._datasets = body.datasets

    def events(self) -> Iterator[AgentEvent]:
        """Run the agent, one event per step. The last one is an answer or an error."""
        return self._agent.run(self._question, self._datasets)


@router.post("/ask")
def ask(run: Annotated[AgentRun, Depends()]) -> AskResponse:
    """Run the agent to completion and return every step plus the final answer."""
    return summarize(list(run.events()))


@router.post("/ask/stream", response_class=EventSourceResponse)
def ask_stream(run: Annotated[AgentRun, Depends()]) -> Iterator[ServerSentEvent]:
    """Run the agent and send each step as a Server-Sent Event, as it happens.

    Each event is named after its type (`tool_call`, `answer`, ...), and its
    data is the event as JSON, the same as one item of `steps` from /ask. The
    last event is always `answer` or `error`. While the agent waits for Claude,
    FastAPI sends a `: ping` comment every 15 seconds, so that no proxy closes
    the quiet connection. If the client disconnects, the agent stops after the
    step it is on, so it doesn't keep spending API credits.
    """
    for event in run.events():
        yield ServerSentEvent(data=event, event=event["type"])


def summarize(events: list[AgentEvent]) -> AskResponse:
    """Turn the agent's events into the /ask response."""
    if not events:
        raise InvariantError("the agent must yield at least one event")
    final, steps = events[-1], events[:-1]
    if final["type"] == "answer":
        return AskResponse(ok=True, answer=final["text"], charts=final["charts"], steps=steps)
    if final["type"] == "error":
        return AskResponse(ok=False, answer=final["message"], charts=final["charts"], steps=steps)
    raise InvariantError(f"the last event must be an answer or an error, got {final['type']}")


def llm_from_env() -> tuple[LLMClient | None, str]:
    """The real Claude client, or None and the reason it can't be built."""
    try:
        client = claude_client_from_env()
    except AgentConfigError as exc:
        return None, str(exc)
    return client, ""


def create_app(store: DataStore | None = None, llm: LLMClient | None = None) -> FastAPI:
    """Build the app. Tests pass an in-memory store and a fake model client.

    Args:
        store: Where datasets live. Default: DuckDB at DUCKDB_PATH (or in memory).
        llm: The model client. Default: Claude, if ANTHROPIC_API_KEY is set.
    """
    if store is None:
        store = DataStore(os.getenv("DUCKDB_PATH", ":memory:"))
    llm_problem = ""
    if llm is None:
        llm, llm_problem = llm_from_env()
    app = FastAPI(title="AI Data Analyst", version=__version__)
    app.state.services = Services(store=store, llm=llm, llm_problem=llm_problem)
    app.include_router(router)
    return app


load_dotenv()
app = create_app()

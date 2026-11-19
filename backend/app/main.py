"""The web API (FastAPI).

Endpoints in step 1:
  GET  /health                     -> is the server up?
  POST /datasets                   -> upload a CSV, get its schema back
  GET  /datasets                   -> list uploaded datasets
  GET  /datasets/{name}            -> schema, row count and sample rows
  POST /query                      -> run one read-only SQL query
  POST /ask                        -> ask the AI agent a question (step 2)

The agent calls the same DataStore methods as its "tools".
"""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent.orchestrator import DataAnalystAgent
from .config import load_dotenv
from .datastore import DatasetError, DataStore
from .sql_guard import UnsafeSQLError

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


class QueryRequest(BaseModel):
    """Pydantic validates the JSON body for us: wrong types or max_rows out of range -> 422."""

    sql: str = Field(..., examples=["SELECT region, SUM(revenue) FROM sales GROUP BY 1"])
    max_rows: int = Field(200, ge=1, le=5000)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    datasets: list[str] | None = Field(None, description="Limit to these datasets (default: all).")


def create_app(
    store: DataStore | None = None,
    agent_factory: Callable[[DataStore], DataAnalystAgent] | None = None,
) -> FastAPI:
    """App factory: tests pass their own in-memory store (and a fake agent),
    production uses the defaults."""
    app = FastAPI(title="AI Data Analyst", version="0.2.0")
    app.state.store = store or DataStore(os.getenv("DUCKDB_PATH", ":memory:"))
    app.state.agent_factory = agent_factory or DataAnalystAgent

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/datasets", status_code=201)
    async def upload_dataset(file: UploadFile) -> dict:
        if not (file.filename or "").lower().endswith(".csv"):
            raise HTTPException(400, "Please upload a .csv file.")
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File is larger than 50 MB.")
        try:
            return app.state.store.load_csv(file.filename, content)
        except DatasetError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/datasets")
    def list_datasets() -> dict:
        return {"datasets": app.state.store.list_tables()}

    @app.get("/datasets/{name}")
    def get_dataset(name: str) -> dict:
        try:
            return app.state.store.describe(name)
        except DatasetError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/query")
    def query(req: QueryRequest) -> dict:
        try:
            return app.state.store.run_query(req.sql, req.max_rows).to_dict()
        except UnsafeSQLError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/ask")
    def ask(req: AskRequest) -> dict:
        """Run the agent to completion and return every step plus the final answer.
        (Step 3 adds a streaming version so the UI can show steps live.)"""
        store = app.state.store
        if req.datasets:
            unknown = set(req.datasets) - set(store.list_tables())
            if unknown:
                raise HTTPException(404, f"Unknown dataset(s): {sorted(unknown)}")
        try:
            agent = app.state.agent_factory(store)
        except Exception as exc:  # e.g. no API key configured
            raise HTTPException(503, f"Agent unavailable: {exc}") from exc

        events = list(agent.run(req.question, req.datasets))
        final = events[-1] if events else {"type": "error", "message": "No response."}
        return {
            "ok": final["type"] == "answer",
            "answer": final.get("text") or final.get("message"),
            "charts": final.get("charts", []),
            "steps": [e for e in events if e["type"] != "answer"],
        }

    return app


load_dotenv()
app = create_app()

"""Shared fixtures for all tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.datastore import DataStore

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample_sales.csv"


@pytest.fixture
def sample_bytes() -> bytes:
    return SAMPLE.read_bytes()


@pytest.fixture
def store(sample_bytes: bytes) -> DataStore:
    """A fresh in-memory store with the sample data loaded as table `sales`."""
    fresh = DataStore(":memory:")
    _ = fresh.load_csv("sales.csv", sample_bytes)
    return fresh


@pytest.fixture(autouse=True)
def no_real_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never talk to the real API, even if a developer has a key set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("AGENT_EFFORT", raising=False)

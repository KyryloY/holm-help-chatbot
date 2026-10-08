"""Shared pytest fixtures for Holm Help."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from holm_help.config import set_demo_today
from holm_help.fake_model import FakeHolmModel
from holm_help.graph import build_graph
from holm_help.journal import init_journal

os.environ["HOLM_FAKE_MODEL"] = "1"
os.environ["ORDERS_MODE"] = "orders"
os.environ["MODEL"] = "fake"


@pytest.fixture(autouse=True)
def _fixed_clock():
    set_demo_today(date(2026, 10, 8))
    os.environ["ORDERS_MODE"] = "orders"
    yield
    set_demo_today(None)
    os.environ["ORDERS_MODE"] = "orders"


@pytest.fixture
def journal_db(tmp_path: Path) -> Path:
    path = tmp_path / "returns_journal.db"
    init_journal(path)
    return path


@pytest.fixture
def fake_model() -> FakeHolmModel:
    return FakeHolmModel()


@pytest.fixture
def memory_graph(fake_model: FakeHolmModel):
    from langgraph.checkpoint.memory import MemorySaver

    return build_graph(checkpointer=MemorySaver(), model=fake_model)

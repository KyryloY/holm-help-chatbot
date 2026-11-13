"""Free-dialog regression scenarios for the capable assistant."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from holm_help.fake_model import FakeHolmModel
from holm_help.graph import build_graph, initial_state
from holm_help.journal import init_journal


@pytest.fixture
def graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    journal = tmp_path / "j.db"
    tickets = tmp_path / "t.db"
    init_journal(journal)
    monkeypatch.setattr("holm_help.tools.JOURNAL_DB", journal)
    monkeypatch.setattr("holm_help.graph.TICKETS_DB", tickets)
    return build_graph(checkpointer=MemorySaver(), model=FakeHolmModel())


@pytest.mark.asyncio
async def test_free_smalltalk(graph):
    result = await graph.ainvoke(
        initial_state("Good morning"),
        config={"configurable": {"thread_id": "st"}},
    )
    assert "assistant" in result["visited_nodes"]
    assert "Holm Help" in (result.get("reply") or "")


@pytest.mark.asyncio
async def test_return_without_id_then_id(graph):
    config = {"configurable": {"thread_id": "ret-slot"}}
    first = await graph.ainvoke(
        initial_state("I want to return an item", thread_id="ret-slot"),
        config=config,
    )
    assert first.get("awaiting_slot") == "order_id"
    second = await graph.ainvoke(
        initial_state("H-1048", thread_id="ret-slot"),
        config=config,
    )
    assert "create_return" in second["visited_nodes"]
    assert second.get("label_number")

"""Assistant-loop and multi-turn slot-filling tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from holm_help.fake_model import FakeHolmModel
from holm_help.graph import build_graph, initial_state
from holm_help.journal import init_journal


@pytest.fixture
def graph_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    journal = tmp_path / "returns_journal.db"
    tickets = tmp_path / "tickets.db"
    init_journal(journal)
    monkeypatch.setenv("ORDERS_MODE", "orders")
    monkeypatch.setattr("holm_help.config.JOURNAL_DB", journal)
    monkeypatch.setattr("holm_help.tools.JOURNAL_DB", journal)
    monkeypatch.setattr("holm_help.graph.TICKETS_DB", tickets)
    monkeypatch.setattr("holm_help.tickets.TICKETS_DB", tickets)
    graph = build_graph(checkpointer=MemorySaver(), model=FakeHolmModel())
    return graph, journal


@pytest.mark.asyncio
async def test_list_orders_no_found_false(graph_env):
    graph, _ = graph_env
    config = {"configurable": {"thread_id": "list1"}}
    result = await graph.ainvoke(
        initial_state("give me list of existing orders", thread_id="list1"),
        config=config,
    )
    reply = (result.get("reply") or "").lower()
    assert "found: false" not in reply
    assert "ask_slot" not in result["visited_nodes"]
    assert "list_demo_orders" in result["tool_calls"]
    assert "h-1042" in reply or "H-1042" in (result.get("reply") or "")
    assert "demo" in reply or "synthetic" in reply


@pytest.mark.asyncio
async def test_status_without_id_asks_then_continues(graph_env):
    graph, _ = graph_env
    thread = "slot-status"
    config = {"configurable": {"thread_id": thread}}
    first = await graph.ainvoke(
        initial_state("Where is my order?", thread_id=thread),
        config=config,
    )
    assert "ask_slot" in first["visited_nodes"]
    assert first.get("awaiting_slot") == "order_id"
    assert "found: false" not in (first.get("reply") or "").lower()

    second = await graph.ainvoke(
        initial_state("H-1042", thread_id=thread),
        config=config,
    )
    assert second.get("order_found") is True
    assert (second.get("order") or {}).get("status") == "in_transit"
    assert "in_transit" in (second.get("reply") or "") or "in transit" in (
        second.get("reply") or ""
    ).lower()


@pytest.mark.asyncio
async def test_policy_via_tools(graph_env):
    graph, _ = graph_env
    result = await graph.ainvoke(
        initial_state("What is your return policy?", thread_id="pol"),
        config={"configurable": {"thread_id": "pol"}},
    )
    assert "read_return_policy" in result["tool_calls"]
    assert "14" in (result.get("reply") or "")

"""Local ticket handoff tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from holm_help.fake_model import FakeHolmModel
from holm_help.graph import build_graph, initial_state
from holm_help.tickets import count_tickets, create_ticket, init_tickets


def test_create_ticket_local(tmp_path: Path):
    db = tmp_path / "tickets.db"
    init_tickets(db)
    ticket = create_ticket(
        thread_id="t1",
        summary="Need a human",
        order_id="H-1042",
        db_path=db,
    )
    assert ticket["id"].startswith("TICKET-")
    assert ticket["status"] == "open"
    assert ticket["simulated"] is True
    assert count_tickets(db) == 1


@pytest.mark.asyncio
async def test_handoff_creates_ticket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tickets = tmp_path / "tickets.db"
    monkeypatch.setattr("holm_help.graph.TICKETS_DB", tickets)
    monkeypatch.setattr("holm_help.tickets.TICKETS_DB", tickets)
    graph = build_graph(checkpointer=MemorySaver(), model=FakeHolmModel())
    result = await graph.ainvoke(
        initial_state("I want to speak to a human agent", thread_id="h1"),
        config={"configurable": {"thread_id": "h1"}},
    )
    assert "handoff" in result["visited_nodes"]
    assert result.get("ticket_id", "").startswith("TICKET-")
    assert count_tickets(tickets) == 1
    assert "TICKET-" in (result.get("reply") or "")

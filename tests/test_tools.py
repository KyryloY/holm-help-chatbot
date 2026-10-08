"""Tool behavior tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from holm_help.exceptions import OrdersServiceUnavailable
from holm_help.tools import create_return, lookup_order, read_return_policy


def test_lookup_unknown_order_found_false():
    result = lookup_order("H-9999")
    assert result == {"found": False, "order_id": "H-9999"}


def test_lookup_known_order():
    result = lookup_order("H-1042")
    assert result["found"] is True
    assert result["order"]["status"] == "in_transit"
    assert result["order"]["amount_eur_cents"] == 8900


def test_lookup_raises_when_orders_down(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORDERS_MODE", "down")
    with pytest.raises(OrdersServiceUnavailable):
        lookup_order("H-1042")


def test_read_return_policy_complete():
    text = read_return_policy()
    assert "14th calendar day" in text
    assert "EUR 150" in text
    assert "does not issue refunds" in text.lower() or "does **not** issue refunds" in text


def test_create_return_idempotent(tmp_path: Path):
    db = tmp_path / "j.db"
    first = create_return("H-1048", journal_db=db)
    second = create_return("H-1048", journal_db=db)
    assert first["label_number"] == second["label_number"]
    assert second["idempotent_hit"] is True
    assert first["label_number"].startswith("SIM-LABEL-")

"""Tests for slot filling and list-orders intent detection."""

from __future__ import annotations

from holm_help.slots import (
    clarify_order_id_message,
    classify_intent_heuristic,
    extract_order_id,
    is_list_orders_request,
    needs_order_id,
)


def test_extract_order_id():
    assert extract_order_id("Where is H-1042?") == "H-1042"
    assert extract_order_id("hello", hint="H-1107") == "H-1107"
    assert extract_order_id("no id here") is None


def test_list_orders_request_detection():
    assert is_list_orders_request("give me list of existing orders") is True
    assert is_list_orders_request("Where is order H-1042?") is False


def test_needs_order_id():
    assert needs_order_id("orders", None) is True
    assert needs_order_id("return", None) is True
    assert needs_order_id("orders", "H-1042") is False
    assert needs_order_id("list_orders", None) is False
    assert needs_order_id("smalltalk", None) is False


def test_classify_list_orders():
    result = classify_intent_heuristic("give me list of exisitng orders")
    assert result["intent"] == "list_orders"


def test_clarify_message():
    assert "H-1042" in clarify_order_id_message("orders")
    assert "return" in clarify_order_id_message("return").lower()

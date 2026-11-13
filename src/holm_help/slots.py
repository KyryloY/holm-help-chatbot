"""Slot extraction and missing-order-ID policy for multi-turn chat."""

from __future__ import annotations

import re
from typing import Any, Literal

ORDER_ID_RE = re.compile(r"\bH-\d{4}\b", re.I)

IntentName = Literal[
    "orders",
    "return",
    "policy",
    "list_orders",
    "smalltalk",
    "handoff",
    "blocked",
]

# Intents that require a concrete order ID before tools/decide.
INTENTS_REQUIRING_ORDER_ID = frozenset({"orders", "return"})


def extract_order_id(text: str, hint: str | None = None) -> str | None:
    """Return the first H-#### order ID from text or an explicit hint."""
    if hint:
        cleaned = str(hint).strip().upper()
        if ORDER_ID_RE.fullmatch(cleaned) or ORDER_ID_RE.search(cleaned):
            match = ORDER_ID_RE.search(cleaned)
            return match.group(0).upper() if match else cleaned
    match = ORDER_ID_RE.search(text or "")
    return match.group(0).upper() if match else None


def is_list_orders_request(text: str) -> bool:
    lower = (text or "").lower()
    if "list" in lower and "order" in lower:
        return True
    if any(
        phrase in lower
        for phrase in (
            "existing orders",
            "all orders",
            "which orders",
            "what orders",
            "show orders",
            "demo orders",
        )
    ):
        return True
    return False


def classify_intent_heuristic(text: str) -> dict[str, Any]:
    """Rule-based intent used by the fake model and as a safe fallback."""
    lower = (text or "").lower()
    order_id = extract_order_id(text)

    if any(w in lower for w in ("handoff", "human agent", "speak to a person", "real person")):
        return {"intent": "handoff", "order_id": order_id}

    if is_list_orders_request(text):
        return {"intent": "list_orders", "order_id": None}

    # Policy before return so "return policy" is not treated as a return request.
    if any(
        w in lower
        for w in ("policy", "how long", "return window", "refund policy", "return policy")
    ):
        return {"intent": "policy", "order_id": order_id}

    if any(w in lower for w in ("return", "send back", "take back")):
        return {"intent": "return", "order_id": order_id}

    if order_id or any(
        w in lower for w in ("where is", "status", "track", "shipment", "order")
    ):
        return {"intent": "orders", "order_id": order_id}

    if any(w in lower for w in ("hello", "hi ", "hi!", "thanks", "thank you", "good morning")):
        return {"intent": "smalltalk", "order_id": None}

    return {"intent": "smalltalk", "order_id": order_id}


def needs_order_id(intent: str | None, order_id: str | None) -> bool:
    return intent in INTENTS_REQUIRING_ORDER_ID and not order_id


def clarify_order_id_message(intent: str | None) -> str:
    if intent == "return":
        return (
            "I can help with a simulated return, but I need an order ID "
            "(for example H-1048). Please reply with the order ID."
        )
    return (
        "I can look up a synthetic order, but I need an order ID "
        "(for example H-1042). Please reply with the order ID, "
        "or ask me to list the demo orders."
    )

"""LangGraph state for Holm Help."""

from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


RouteName = Literal[
    "orders",
    "policy",
    "return",
    "list_orders",
    "smalltalk",
    "handoff",
    "blocked",
    "ask_slot",
]

DecisionCode = Literal[
    "eligible",
    "needs_approval",
    "window_closed",
    "not_delivered",
    "already_returned",
    "unknown_order",
    "service_unavailable",
]


class SupportState(TypedDict):
    """Explicit graph state. Never store full payment-card numbers here."""

    user_message: str
    sanitized_message: str
    messages: Annotated[list[AnyMessage], add_messages]
    route: NotRequired[RouteName | str]
    last_intent: NotRequired[str | None]
    awaiting_slot: NotRequired[str | None]
    active_order_id: NotRequired[str | None]
    order_id: NotRequired[str | None]
    order: NotRequired[dict[str, Any] | None]
    order_found: NotRequired[bool]
    policy_text: NotRequired[str | None]
    demo_orders_summary: NotRequired[str | None]
    decision: NotRequired[DecisionCode | str | None]
    decision_reason: NotRequired[str | None]
    approval_status: NotRequired[str | None]
    label_number: NotRequired[str | None]
    reply: NotRequired[str]
    blocked_reason: NotRequired[str | None]
    card_masked: NotRequired[str | None]
    error: NotRequired[str | None]
    pending_approval: NotRequired[bool]
    thread_id: NotRequired[str | None]
    ticket_id: NotRequired[str | None]
    visited_nodes: NotRequired[list[str]]
    tool_calls: NotRequired[list[str]]
    # Internal routing flags for the assistant loop.
    next_action: NotRequired[str | None]

"""LangGraph state for Holm Help."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


RouteName = Literal[
    "orders",
    "policy",
    "return",
    "smalltalk",
    "handoff",
    "blocked",
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
    route: NotRequired[RouteName | str]
    order_id: NotRequired[str | None]
    order: NotRequired[dict[str, Any] | None]
    order_found: NotRequired[bool]
    policy_text: NotRequired[str | None]
    decision: NotRequired[DecisionCode | str | None]
    decision_reason: NotRequired[str | None]
    approval_status: NotRequired[str | None]
    label_number: NotRequired[str | None]
    reply: NotRequired[str]
    blocked_reason: NotRequired[str | None]
    card_masked: NotRequired[str | None]
    error: NotRequired[str | None]
    pending_approval: NotRequired[bool]
    visited_nodes: NotRequired[list[str]]
    tool_calls: NotRequired[list[str]]
